# Source at the repository root in Git Bash. Keep the Step 11 helper for rollback.
dc12() {
  docker compose --env-file .env.compose \
    --env-file services/embedding-service/contract.env \
    -f docker-compose.yml \
    -f docker-compose.minio.yml \
    -f docker-compose.worker.yml \
    -f docker-compose.docling.yml \
    -f docker-compose.embedding.yml \
    -f docker-compose.runtime.yml "$@"
}
