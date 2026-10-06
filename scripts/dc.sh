# Source from repository root in Git Bash. Includes all four overlays.
dc() {
  docker compose --env-file .env.compose \
    -f docker-compose.yml \
    -f docker-compose.minio.yml \
    -f docker-compose.worker.yml \
    -f docker-compose.docling.yml "$@"
}
