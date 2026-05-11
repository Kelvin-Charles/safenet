#!/bin/bash
# SafeNet RADIUS Manager - Management Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$PROJECT_DIR/.env"
    set +a
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}ℹ $1${NC}"
}

# Check if docker-compose is available
check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed"
        exit 1
    fi
    
    if ! docker compose version &> /dev/null; then
        print_error "Docker Compose is not installed"
        exit 1
    fi
    
    print_success "Docker and Docker Compose are available"
}

# Start services
start() {
    print_info "Starting SafeNet services..."
    docker compose up -d
    print_success "Services started"
    print_info "Web interface: http://localhost:5000"
}

# Stop services
stop() {
    print_info "Stopping SafeNet services..."
    docker compose down
    print_success "Services stopped"
}

# Restart services
restart() {
    print_info "Restarting SafeNet services..."
    docker compose restart
    print_success "Services restarted"
}

# View logs
logs() {
    service=${1:-all}
    if [ "$service" = "all" ]; then
        docker compose logs -f
    else
        docker compose logs -f "$service"
    fi
}

# Check status
status() {
    print_info "SafeNet Services Status:"
    docker compose ps
}

# Backup database
backup() {
    backup_dir="$PROJECT_DIR/backups"
    mkdir -p "$backup_dir"
    
    timestamp=$(date +%Y%m%d_%H%M%S)
    backup_file="$backup_dir/safenet_backup_$timestamp.sql"
    
    print_info "Creating database backup..."
    
    if docker compose exec -T db mysqldump -u radius -p"${DB_PASSWORD:?Set DB_PASSWORD in .env}" radius > "$backup_file"; then
        gzip "$backup_file"
        print_success "Backup created: ${backup_file}.gz"
    else
        print_error "Backup failed"
        exit 1
    fi
}

# Restore database
restore() {
    if [ -z "$1" ]; then
        print_error "Usage: $0 restore <backup-file>"
        exit 1
    fi
    
    backup_file="$1"
    
    if [ ! -f "$backup_file" ]; then
        print_error "Backup file not found: $backup_file"
        exit 1
    fi
    
    print_info "Restoring database from $backup_file..."
    
    if [[ "$backup_file" == *.gz ]]; then
        gunzip -c "$backup_file" | docker compose exec -T db mysql -u radius -p"${DB_PASSWORD:?Set DB_PASSWORD in .env}" radius
    else
        docker compose exec -T db mysql -u radius -p"${DB_PASSWORD:?Set DB_PASSWORD in .env}" radius < "$backup_file"
    fi
    
    print_success "Database restored"
}

# Test RADIUS
test_radius() {
    username=${1:-testuser}
    password=${2:-testpass123}
    
    print_info "Testing RADIUS authentication..."
    print_info "Username: $username"
    
    docker compose exec freeradius radtest "$username" "$password" localhost 0 testing123
}

# Debug RADIUS
debug_radius() {
    print_info "Starting FreeRADIUS in debug mode..."
    print_info "Press Ctrl+C to stop"
    docker compose exec freeradius freeradius -X
}

# Database shell
db_shell() {
    print_info "Connecting to database..."
    docker compose exec db mysql -u radius -p"${DB_PASSWORD:?Set DB_PASSWORD in .env}" radius
}

# Initialize database
init_db() {
    print_info "Initializing database..."
    docker compose exec web flask init-db
    print_success "Database initialized"
}

# Update system
update() {
    print_info "Updating SafeNet..."
    
    # Pull latest changes
    if [ -d .git ]; then
        git pull
    fi
    
    # Rebuild containers
    docker compose build --no-cache
    
    # Restart services
    docker compose down
    docker compose up -d
    
    print_success "Update complete"
}

# Clean up
clean() {
    print_info "Cleaning up Docker resources..."
    docker compose down --rmi all --volumes
    print_success "Cleanup complete"
}

# Show help
show_help() {
    cat << EOF
SafeNet RADIUS Manager - Management Script

Usage: $0 <command> [options]

Commands:
    start               Start all services
    stop                Stop all services
    restart             Restart all services
    status              Show service status
    logs [service]      Show logs (all or specific service)
    
    backup              Create database backup
    restore <file>      Restore database from backup
    
    test [user] [pass]  Test RADIUS authentication
    debug               Run FreeRADIUS in debug mode
    
    db                  Open database shell
    init-db             Initialize database
    
    update              Update system and rebuild
    clean               Clean up all Docker resources
    
    help                Show this help message

Examples:
    $0 start
    $0 logs web
    $0 test myuser mypass
    $0 backup
    $0 restore backups/safenet_backup_20240101_120000.sql.gz

EOF
}

# Main
case "${1:-help}" in
    start)
        check_docker
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs "$2"
        ;;
    backup)
        backup
        ;;
    restore)
        restore "$2"
        ;;
    test)
        test_radius "$2" "$3"
        ;;
    debug)
        debug_radius
        ;;
    db)
        db_shell
        ;;
    init-db)
        init_db
        ;;
    update)
        update
        ;;
    clean)
        clean
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        print_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac


