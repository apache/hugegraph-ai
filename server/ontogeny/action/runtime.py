# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""ActionRuntime: the five-stage write path (parameters -> rules -> policy ->
effects -> audit), plus transactional outbox enqueue.

Everything mutating object state flows through here -- REST, MCP, CLI and the
evolution replay engine share this single door. Function-backed actions never
write directly either: the sandbox returns an *effect plan* which this runtime
applies, keeping transactions/audit/policy inside the engine.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Callable

from sqlalchemy import select

from ..core import expr as _expr
from ..core.models import (
    ArchiveObjectEffect,
    CreateObjectEffect,
    EmitEventEffect,
    ModifyLinkedEffect,
    ModifyTargetEffect,
    SetLinkEffect,
    WebhookEffect,
)
from ..errors import (
    ConflictError,
    NotFoundError,
    OOError,
    RuleRejectedError,
    TypeMismatchError,
)
from ..policy.engine import PolicyEngine
from ..stores.repo import ObjectRepository, utcnow
from .models import OutboxRow, RevisionRow

EffectRunner = Callable[..., Any]  # async (session, entry, params, ctx) -> list[dict]


class Literal:
    """Marks an already-computed value in a function-provided effect plan.

    Declarative effects carry *expressions* (authored, statically validated);
    function plans carry *data* (computed at runtime). Without this distinction
    a plain value like "EQ-01" would be parsed as `EQ - 01`. Plan authors mark
    engine-evaluated values explicitly with {"$expr": "..."}; everything else is
    taken verbatim.
    """

    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Literal({self.value!r})"


def _jsonable(value: Any) -> Any:
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


class ActionRuntime:
    def __init__(
        self,
        compiled,
        repo: ObjectRepository,
        policy: PolicyEngine,
        settings,
        function_runner: EffectRunner | None = None,
    ) -> None:
        self.compiled = compiled
        self.repo = repo
        self.policy = policy
        self.settings = settings
        self.function_runner = function_runner
        # newId() sequence shared by every execution on this runtime: a fresh
        # seed per execute() made two consecutive creates produce the same id
        # (PO-000001 twice). The insert guard turns restart-time collisions
        # into a 409 instead of duplicate alive rows.
        self._id_seq: dict[str, int] = {}

    # ------------------------------------------------------------ parameters

    def _bind_parameters(self, action, raw: dict[str, Any]) -> dict[str, Any]:
        spec = action.spec
        params: dict[str, Any] = {}
        for name, pdef in spec.parameters.items():
            value = raw.get(name, pdef.default)
            if value is None:
                if pdef.required:
                    raise TypeMismatchError(f"missing required parameter {name!r}")
                params[name] = None
                continue
            params[name] = pdef.ptype().coerce(value, prop=name)
        unknown = set(raw) - set(spec.parameters)
        if unknown:
            raise TypeMismatchError(f"unknown parameters: {sorted(unknown)}")
        return params

    # ---------------------------------------------------------------- public

    async def validate(
        self, session, action_name: str, principal: dict,
        parameters: dict[str, Any], target_id: str | None,
    ) -> dict[str, Any]:
        """Dry-run: parameters + rules + policy WITHOUT any writes."""
        action = self.compiled.actions.get(action_name)
        if action is None:
            raise NotFoundError(f"unknown action {action_name!r}")
        params = self._bind_parameters(action, parameters)
        target = await self.repo.get(session, action.spec.target, target_id) if target_id else None
        ctx = _expr.ExprContext(target=target, parameters=params, principal=principal)
        rule_results = []
        for rule in action.spec.rules:
            ok = bool(_expr.evaluate(rule.expr, ctx))
            rule_results.append({"expr": rule.expr, "ok": ok, "message": None if ok else (rule.message or "rule rejected")})
        decision = self.policy.decide(principal, action_name, target)
        return {"parameters": params, "rules": rule_results, "policy": {"allow": decision.allow, "reason": decision.reason}}

    async def execute(
        self,
        session,
        action_name: str,
        principal: dict,
        parameters: dict[str, Any],
        target_id: str | None = None,
        *,
        expected_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> RevisionRow:
        action = self.compiled.actions.get(action_name)
        if action is None:
            raise NotFoundError(f"unknown action {action_name!r}")

        # 1) idempotent replay
        if idempotency_key:
            existing = (await session.execute(
                select(RevisionRow).where(RevisionRow.idempotency_key == idempotency_key)
            )).scalar_one_or_none()
            if existing is not None:
                if existing.outcome == "executed":
                    return existing
                raise ConflictError(
                    f"idempotency key {idempotency_key!r} belongs to a {existing.outcome} revision"
                )

        params = self._bind_parameters(action, parameters)

        async def _record(outcome: str, message: str | None, before=None, after=None,
                          rules_hit=None, decision=None, obj_id: str | None = None) -> RevisionRow:
            rev = RevisionRow(
                action=action_name, object_type=action.spec.target,
                object_id=str(obj_id or target_id or ""),
                principal=str(principal.get("id", "anonymous")),
                params=_jsonable(params), before=_jsonable(before), after=_jsonable(after),
                rules_hit=rules_hit, policy_decision=None if decision is None
                else {"allow": decision.allow, "reason": decision.reason},
                outcome=outcome, message=message, idempotency_key=idempotency_key,
            )
            session.add(rev)
            await session.flush()
            return rev

        # 2) load + rules (evaluated INSIDE the transaction on latest state)
        target: dict | None = None
        if target_id is not None:
            target = await self.repo.get(session, action.spec.target, target_id, for_update=True)
            if target is None:
                raise NotFoundError(f"{action.spec.target}/{target_id} not found (or archived)")
        ctx = _expr.ExprContext(target=target or {}, parameters=params, principal=principal,
                                now=utcnow(), _seq=self._id_seq)
        rules_hit = []
        for rule in action.spec.rules:
            ok = bool(_expr.evaluate(rule.expr, ctx))
            rules_hit.append({"expr": rule.expr, "ok": ok})
            if not ok:
                rev = await _record("rejected_rule", rule.message or "rule rejected", before=target, rules_hit=rules_hit)
                # Rules run before any data write, so the session holds nothing but
                # this audit row: commit it here and the rejection is recorded no
                # matter which shell (REST/MCP/CLI/eval) invoked the action.
                await session.commit()
                raise RuleRejectedError(
                    rule.message or f"rule rejected: {rule.expr}",
                    details={"revision_id": rev.id, "rule": rule.expr},
                )

        # 3) policy at the last meter
        decision = self.policy.decide(principal, action_name, target)
        if not decision.allow:
            rev = await _record("denied_policy", decision.reason, before=target, rules_hit=rules_hit, decision=decision)
            await session.commit()  # same reasoning as the rule-rejection path
            from ..errors import PolicyDeniedError

            raise PolicyDeniedError(
                f"policy denied {action_name!r}: {decision.reason}",
                details={"revision_id": rev.id},
            )

        # 4) effect plan (declarative, or sandbox-provided for function-backed)
        effects: list[Any] = list(action.spec.effects)
        if action.spec.execution is not None:
            if self.function_runner is None:
                raise OOError("function-backed action requires a configured function runner")
            plan = await self.function_runner(session, action.spec.execution.entry, params, ctx)
            effects = [self._materialize_plan_entry(entry) for entry in plan]

        before = dict(target) if target else None
        after: dict | None = None
        created_id: str | None = None
        linked_pairs: list[tuple[str, str]] = []  # (object_type, id) changed via modify-linked
        ts = utcnow()

        for eff in effects:
            if getattr(eff, "when", None) is not None and not bool(_expr.evaluate(eff.when, ctx)):
                continue
            outcome = await self._apply_effect(session, action, eff, ctx, target_id, expected_revision if after is None and before else None, ts)
            if outcome is not None:
                after, created_id = outcome[0], outcome[1] or created_id
                linked_pairs.extend(outcome[2] or [])

        # 5) audit revision + outbox (same transaction)
        effective_id = created_id or target_id
        if after is None:
            after = await self.repo.get(session, action.spec.target, effective_id)
        rev = await _record("executed", None, before=before, after=after, rules_hit=rules_hit, decision=decision, obj_id=effective_id)
        for op, oid, payload in self._outbox_events(
            action, effects, before, after, effective_id, ctx, linked_pairs,
        ):
            session.add(OutboxRow(
                # linked-object events carry their own type in the payload
                object_type=payload.get("object_type", action.spec.target),
                object_id=oid or "", op=op,
                payload=_jsonable(payload), revision_id=rev.id,
            ))
        return rev

    # --------------------------------------------------------------- effects

    def _eval_value(self, expr_src: Any, ctx: _expr.ExprContext, current_target: dict) -> Any:
        if isinstance(expr_src, Literal):
            return expr_src.value  # data from a function plan, not an expression
        bare = _expr.is_bare_identifier(expr_src)
        if bare is not None and bare not in current_target:
            return bare  # enum literal, e.g. `status: OPEN`
        return _expr.evaluate(expr_src, ctx)

    def _coerce_props(self, object_type: str, values: dict[str, Any]) -> dict[str, Any]:
        """Coerce effect results to the declared property types.

        Values can come from a function plan (arbitrary JSON), so an unchecked
        write could store a string in an integer column. Coercing here means a
        type error surfaces as a rule-style rejection, not silent corruption.
        """
        obj = self.compiled.objects.get(object_type)
        if obj is None:
            return values
        out: dict[str, Any] = {}
        for prop, value in values.items():
            pdef = obj.spec.properties.get(prop)
            out[prop] = pdef.ptype().coerce(value, prop=f"{object_type}.{prop}") if pdef else value
        return out

    async def _apply_effect(self, session, action, eff, ctx, target_id, expected_revision, ts):

        if isinstance(eff, ModifyTargetEffect):
            changes = self._coerce_props(action.spec.target, {
                k: self._eval_value(v, ctx, ctx.target or {}) for k, v in eff.set.items()
            })
            new = await self.repo.action_update(
                session, action.spec.target, target_id, changes, ts, expected_revision=expected_revision,
            )
            ctx.target = new
            return new, None, []

        if isinstance(eff, CreateObjectEffect):
            props = self._coerce_props(action.spec.target, {
                k: self._eval_value(v, ctx, ctx.target or {}) for k, v in eff.properties.items()
            })
            created = await self.repo.action_insert(session, action.spec.target, props, ts)
            pk = self.compiled.objects[action.spec.target].spec.primaryKey[0]
            created_id = str(created[pk]) if created else None
            ctx.target = created
            return created, created_id, []

        if isinstance(eff, ArchiveObjectEffect):
            await self.repo.archive(session, action.spec.target, target_id, ts)
            return {"archived": True}, None, []

        if isinstance(eff, SetLinkEffect):
            from ..core.models import ForeignKeyJoin

            lnk = self.compiled.links[eff.link]
            if isinstance(lnk.spec.join, ForeignKeyJoin):
                # FK links: the FK column ALWAYS lives on the link target's
                # table (same convention fk_linked_ids / fk_link_pairs use),
                # so the only supported direction is acting on that side.
                # Picking the side relative to the actor (as this used to)
                # made acting *from* the carrier raise for everyone.
                (tgt_side, _src_side), = lnk.spec.join.keys.items()
                fk_obj, fk_prop = tgt_side.split(".", 1)
                if fk_obj != action.spec.target:
                    raise OOError(
                        f"set-link on FK link {eff.link!r} is only supported from the FK-carrying side"
                    )
                fk_written = False
                for entry in eff.add:
                    resolved = {k: self._eval_value(str(v), ctx, ctx.target or {}) for k, v in entry.model_dump(exclude_none=True).items()}
                    if not resolved:
                        continue
                    await self.repo.action_update(session, action.spec.target, target_id, {fk_prop: next(iter(resolved.values()))}, ts)
                    fk_written = True
                for entry in eff.remove:
                    if fk_written:
                        continue  # the add already re-pointed the FK: that IS the removal
                    resolved = {k: self._eval_value(str(v), ctx, ctx.target or {}) for k, v in entry.model_dump(exclude_none=True).items()}
                    cur = (ctx.target or {}).get(fk_prop)
                    if resolved and cur is not None and str(cur) == str(next(iter(resolved.values()))):
                        # FK membership has no "absent" row: removing = clearing the FK
                        await self.repo.action_update(session, action.spec.target, target_id, {fk_prop: None}, ts)
            else:
                for entry in eff.add:
                    resolved = {k: self._eval_value(str(v), ctx, ctx.target or {}) for k, v in entry.model_dump(exclude_none=True).items()}
                    if not resolved:
                        continue
                    # join-table links: entry keys are target-side props; the single
                    # resolved value is the destination PK (v0)
                    dst = next(iter(resolved.values()))
                    await self.repo.link_add(session, eff.link, str(target_id), str(dst), ts)
                for entry in eff.remove:
                    resolved = {k: self._eval_value(str(v), ctx, ctx.target or {}) for k, v in entry.model_dump(exclude_none=True).items()}
                    if resolved:
                        await self.repo.link_remove(session, eff.link, str(target_id), str(next(iter(resolved.values()))), ts)
            return None, None, []

        if isinstance(eff, ModifyLinkedEffect):
            lnk = self.compiled.links[eff.link]
            from_source = lnk.spec.source == action.spec.target
            other = lnk.spec.target if from_source else lnk.spec.source
            linked_ids = await self._linked_ids(session, eff.link, target_id, from_source)
            for oid in linked_ids:
                changes = self._coerce_props(other, {
                    k: self._eval_value(v, ctx, ctx.target or {}) for k, v in eff.set.items()
                })
                await self.repo.action_update(session, other, oid, changes, ts)
            # linked rows changed: the caller emits outbox events for them so the
            # derivation worker re-materializes their function-derived properties
            return None, None, [(other, oid) for oid in linked_ids]

        # WebhookEffect / EmitEventEffect: no synchronous side effects here;
        # they are enqueued to the outbox below.
        return None, None, []

    async def _linked_ids(self, session, link_name: str, obj_id: str, from_source: bool) -> list[str]:
        from ..core.models import ForeignKeyJoin

        lnk = self.compiled.links[link_name]
        if isinstance(lnk.spec.join, ForeignKeyJoin):
            return await self.repo.fk_linked_ids(session, link_name, obj_id, from_source=from_source)
        members = await self.repo.link_members(
            session, link_name, src_id=obj_id if from_source else None, dst_id=obj_id if not from_source else None,
        )
        return [dst if from_source else src for src, dst in members]

    def _materialize_plan_entry(self, entry: dict):
        """Function-backed effect plans arrive as JSON dicts.

        Validated strictly against the same Effect union as declarative effects,
        then their property values are interpreted as *data*: only an explicit
        {"$expr": "..."} wrapper is evaluated by the engine.
        """
        from pydantic import TypeAdapter

        from ..core.models import Effect

        fields = ("properties", "set")
        data_keys: dict[str, set[str]] = {f: set() for f in fields}
        sanitized = dict(entry)
        for field in fields:
            raw = entry.get(field)
            if not isinstance(raw, dict):
                continue
            clean: dict[str, Any] = {}
            for key, value in raw.items():
                if isinstance(value, dict) and set(value.keys()) == {"$expr"}:
                    clean[key] = str(value["$expr"])  # engine-evaluated
                else:
                    clean[key] = "" if value is None else str(value)
                    data_keys[field].add(key)  # data, not an expression
            sanitized[field] = clean

        eff = TypeAdapter(Effect).validate_python(sanitized)
        for field in fields:
            if not data_keys[field] or not hasattr(eff, field):
                continue
            original = entry[field]
            setattr(eff, field, {
                k: (Literal(original[k]) if k in data_keys[field] else v)
                for k, v in getattr(eff, field).items()
            })
        return eff

    def _outbox_events(self, action, effects, before, after, obj_id, ctx, linked_pairs=None):
        events: list[tuple[str, str | None, dict]] = []
        for eff in effects:
            if getattr(eff, "when", None) is not None and not bool(_expr.evaluate(eff.when, ctx)):
                continue
            if isinstance(eff, WebhookEffect):
                # store the template; the dispatcher resolves ${VAR} at delivery
                # time so a missing env var cannot abort a business transaction
                # (fix the config and replay the event instead)
                events.append(("event", obj_id, {
                    "kind": "webhook", "url_template": eff.url, "object_id": obj_id,
                }))
            elif isinstance(eff, EmitEventEffect):
                events.append(("event", obj_id, {"kind": "emit", "payload": eff.payload}))
        if after is not None and before is None:
            events.append(("upsert", obj_id, {"origin": "action:create"}))
        elif after is not None:
            events.append(("upsert", obj_id, {"origin": "action:modify"}))
        # linked objects changed via modify-linked: their rows moved too, so the
        # derivation worker must re-materialize their function-derived props
        for linked_type, linked_id in (linked_pairs or []):
            events.append(("upsert", linked_id, {"origin": "action:linked", "object_type": linked_type}))
        return events
