# Source this from the repository root in Git Bash: source scripts/dc.sh
# All three overlays are required after the Step 8 handoff.
dc() {
  docker compose --env-file .env.compose \
    -f docker-compose.yml \
    -f docker-compose.minio.yml \
    -f docker-compose.worker.yml "$@"
}
