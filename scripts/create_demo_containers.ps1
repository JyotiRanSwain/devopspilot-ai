# Starts REAL containers that fail in realistic ways, so the dashboard has genuine problems to diagnose.
# Remove them with scripts\remove_demo_containers.ps1
$L = @("--label", "devopspilot.demo=true")
docker run -d @L --name dop-demo-healthy --health-cmd "wget -q -O /dev/null http://localhost/ || exit 1" --health-interval 5s nginx:alpine
docker run -d @L --name dop-demo-unhealthy --health-cmd "wget -q -O /dev/null http://localhost:9999/ || exit 1" --health-interval 5s --health-retries 1 nginx:alpine
docker run -d @L --name dop-demo-crash alpine:3.20 sh -c "echo 'INFO starting api'; echo 'ERROR environment variable DATABASE_URL is not set'; exit 1"
docker run -d @L --name dop-demo-restart-loop --restart=always alpine:3.20 sh -c "echo 'FATAL cannot start worker'; sleep 1; exit 1"
docker run -d @L --name dop-demo-db-down alpine:3.20 sh -c "echo 'psycopg2.OperationalError: could not connect to server: Connection refused (db:5432)'; echo 'password authentication failed for user app'; exit 1"
docker run -d @L --name dop-demo-port-owner -p 18080:80 nginx:alpine
docker run -d @L --name dop-demo-port-conflict -p 18080:80 nginx:alpine
if ($LASTEXITCODE -ne 0) { Write-Host "(expected) the second container could not bind port 18080" }
Write-Host "Done. Open the dashboard and look at the dop-demo-* containers."
