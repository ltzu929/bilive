# bilive Context

This context defines project-specific language for the local bilive fork. It keeps terms aligned across the Pi recording, Windows slicing, dashboard, and upload workflows.

## Language

**Default Test Suite**:
The fast offline regression suite for the active bilive workflow. It requires no real API keys, cloud SDK credentials, real video paths, or external services, and it protects the dashboard-submitted pending worker path, related dashboard contracts, and small compatibility guards for retained legacy entry points.
_Avoid_: Full CI, all tests, cloud tests, manual verification
