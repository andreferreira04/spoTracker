"""App version. Stays 0.0.0 in the repo; the CI workflow patches it when building a release."""
VERSION = "0.0.0"

IS_DEV = VERSION == "0.0.0"  # built locally, not by the release workflow
APP_NAME = "SpoTracker (Dev)" if IS_DEV else "SpoTracker"
