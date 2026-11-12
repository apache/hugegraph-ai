// Lifecycle policies: product owns requirements and tapeouts, fab owns lots,
// steps and tests, customer quality engineers own field failures.
permit(
  principal in Role::"product",
  action == Action::"create-requirement",
  resource
);
permit(
  principal in Role::"product",
  action == Action::"change-requirement",
  resource
) when { resource.status != "CLOSED" };
permit(
  principal in Role::"product",
  action == Action::"create-design-module",
  resource
);
permit(
  principal in Role::"product",
  action == Action::"create-tapeout-version",
  resource
);
permit(
  principal in Role::"product",
  action == Action::"tapeout",
  resource
) when { resource.status == "PLANNED" };
permit(
  principal in Role::"fab",
  action == Action::"start-lot",
  resource
);
permit(
  principal in Role::"fab",
  action == Action::"complete-process-step",
  resource
) when { resource.status != "COMPLETED" };
permit(
  principal in Role::"fab",
  action == Action::"hold-lot",
  resource
) when { resource.status == "RUNNING" };
permit(
  principal in Role::"fab",
  action == Action::"record-wafer-test",
  resource
);
permit(
  principal in Role::"fab",
  action == Action::"retract-wafer-test",
  resource
);
permit(
  principal in Role::"fab",
  action == Action::"reassign-step",
  resource
);
permit(
  principal in Role::"fab",
  action == Action::"raise-yield-alert",
  resource
);
permit(
  principal in Role::"fab",
  action == Action::"record-root-cause",
  resource
);
permit(
  principal in Role::"cqe",
  action == Action::"open-field-failure",
  resource
);
permit(
  principal in Role::"cqe",
  action == Action::"raise-surge-alert",
  resource
);
permit(
  principal in Role::"cqe",
  action == Action::"record-failure-root-cause",
  resource
);
