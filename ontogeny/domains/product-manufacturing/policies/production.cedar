// Production policies: planners own planning and master data, operators run
// the routing, quality staff record inspections.
permit(
  principal in Role::"planner",
  action == Action::"introduce-product",
  resource
);
permit(
  principal in Role::"planner",
  action == Action::"register-work-center",
  resource
);
permit(
  principal in Role::"planner",
  action == Action::"add-bom-line",
  resource
);
permit(
  principal in Role::"planner",
  action == Action::"receive-material",
  resource
);
permit(
  principal in Role::"planner",
  action == Action::"create-production-order",
  resource
);
permit(
  principal in Role::"planner",
  action == Action::"release-production-order",
  resource
) when { resource.status == "PLANNED" };
permit(
  principal in Role::"operator",
  action == Action::"complete-operation",
  resource
) when { resource.status != "COMPLETED" };
permit(
  principal in Role::"quality",
  action == Action::"record-inspection",
  resource
);

permit(
  principal in Role::"planner",
  action == Action::"cancel-production-order",
  resource
);
permit(
  principal in Role::"planner",
  action == Action::"assign-operation",
  resource
);
permit(
  principal in Role::"quality",
  action == Action::"retract-inspection",
  resource
);
