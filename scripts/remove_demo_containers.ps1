$ids = docker ps -aq --filter label=devopspilot.demo=true
if ($ids) { docker rm -f $ids }
