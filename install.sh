#!/usr/bin/env bash
# nsogcd installer
# Run with: curl -fsSL https://raw.githubusercontent.com/loserkidsblink/nsogcd/main/install.sh | sudo bash
# Or:       sudo ./install.sh

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: this installer must be run as root."
    echo "Try: curl -fsSL https://raw.githubusercontent.com/loserkidsblink/nsogcd/main/install.sh | sudo bash"
    exit 1
fi

REPO_URL="${NSOGCD_REPO_URL:-https://github.com/loserkidsblink/nsogcd.git}"
BRANCH="${NSOGCD_BRANCH:-main}"
INSTALL_PREFIX="${INSTALL_PREFIX:-/usr/local}"

echo "=================================================="
echo "  nsogcd - NSO GameCube Controller for Linux"
echo "=================================================="
echo

# Detect OS
OS_ID=""
if [ -f /etc/os-release ]; then
    OS_ID=$(. /etc/os-release && echo "${ID:-unknown}")
fi
echo "Detected OS: $OS_ID"

# Detect package manager and install dependencies
install_deps() {
    echo "Installing dependencies..."

    case "$OS_ID" in
        bazzite|fedora|nobara|silverblue|kinoite)
            # Fedora/RHEL family. Python dependencies live in a dedicated venv.
            if ! command -v python3 >/dev/null; then echo "ERROR: python3 not found"; exit 1; fi
            if command -v rpm-ostree >/dev/null && [ -f /run/ostree-booted ]; then
                echo "OSTree-based system detected. Using a local Python venv."
            else
                dnf install -y python3-pip bluez bluez-tools 2>/dev/null || true
            fi
            ;;
        steamos|holo)
            # Steam Deck SteamOS — read-only by default
            if [ -x /usr/bin/steamos-readonly ] && steamos-readonly status 2>&1 | grep -q enabled; then
                echo "SteamOS read-only filesystem is enabled."
                echo "We'll install the daemon and service to /home (writable) instead of /usr."
                INSTALL_PREFIX=/home/deck/.local
            fi
            ;;
        arch|endeavouros|manjaro|chimeraos)
            pacman -S --needed --noconfirm python python-pip bluez-utils 2>/dev/null || true
            ;;
        ubuntu|debian|pop|linuxmint)
            apt-get update -q
            apt-get install -y python3-venv bluez 2>/dev/null || true
            ;;
        *)
            echo "Warning: unrecognized distro '$OS_ID'. Assuming Python and bluez are available."
            ;;
    esac

    install -d -m 755 "$INSTALL_PREFIX/lib/nsogcd"
    # Bazzite ships python3-evdev but not Python development headers. Make
    # distro packages visible so pip does not try to compile evdev from source.
    python3 -m venv --system-site-packages "$INSTALL_PREFIX/lib/nsogcd/.venv" \
        || { echo "ERROR: python3 venv is unavailable; install your distro's python3-venv package"; exit 1; }
    "$INSTALL_PREFIX/lib/nsogcd/.venv/bin/python" -m pip install --quiet \
        'bumble==0.0.233' \
        || { echo "ERROR: failed to install Python dependencies"; exit 1; }
    if ! "$INSTALL_PREFIX/lib/nsogcd/.venv/bin/python" -c 'import evdev' >/dev/null 2>&1; then
        "$INSTALL_PREFIX/lib/nsogcd/.venv/bin/python" -m pip install --quiet \
            'evdev>=1.7,<2' \
            || { echo "ERROR: evdev is unavailable; install python3-evdev or Python development headers"; exit 1; }
    fi

    echo "Dependencies installed."
}

# Use the downloaded release bundle or local checkout when available. A piped
# installer can still fetch its matching source from GitHub.
fetch_source() {
    SRC_DIR_TEMP=0
    local script_path="${BASH_SOURCE[0]:-}"
    if [ -n "$script_path" ] && [ -f "$script_path" ]; then
        local script_dir
        script_dir=$(cd "$(dirname "$script_path")" && pwd -P)
        if [ -f "$script_dir/daemon/nsogcd.py" ] && \
           [ -f "$script_dir/daemon/gc_controller/ble/bumble_backend.py" ]; then
            SRC_DIR="$script_dir"
            echo "Installing nsogcd from local bundle: $SRC_DIR"
            return
        fi
    fi

    SRC_DIR=$(mktemp -d)
    SRC_DIR_TEMP=1
    echo "Fetching nsogcd from $REPO_URL..."
    if command -v git >/dev/null; then
        git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$SRC_DIR" 2>&1 | tail -3
    else
        # No git? Use curl + tar
        TARBALL_URL="${REPO_URL%.git}/archive/refs/heads/${BRANCH}.tar.gz"
        curl -fsSL "$TARBALL_URL" | tar -xz -C "$SRC_DIR" --strip-components=1
    fi
    echo "Source at: $SRC_DIR"
}

install_files() {
    echo "Installing files..."

    # Stop an older exclusive-HCI unit before replacing it; its stop hook
    # restores bluetooth.service if it was masked at runtime.
    systemctl stop nsogcd 2>/dev/null || true

    install -d -m 755 "$INSTALL_PREFIX/lib/nsogcd"
    install -d -m 755 "$INSTALL_PREFIX/bin"
    install -m 755 "$SRC_DIR/daemon/nsogcd.py" "$INSTALL_PREFIX/lib/nsogcd/nsogcd.py"
    install -m 644 "$SRC_DIR/daemon/pairing_policy.py" "$INSTALL_PREFIX/lib/nsogcd/pairing_policy.py"
    install -d -m 755 "$INSTALL_PREFIX/lib/nsogcd/gc_controller/ble"
    install -m 644 "$SRC_DIR/daemon/gc_controller/__init__.py" "$INSTALL_PREFIX/lib/nsogcd/gc_controller/__init__.py"
    install -m 644 "$SRC_DIR/daemon/gc_controller/ble/__init__.py" "$INSTALL_PREFIX/lib/nsogcd/gc_controller/ble/__init__.py"
    install -m 644 "$SRC_DIR/daemon/gc_controller/ble/bumble_backend.py" "$INSTALL_PREFIX/lib/nsogcd/gc_controller/ble/bumble_backend.py"
    install -m 644 "$SRC_DIR/daemon/gc_controller/ble/sw2_protocol.py" "$INSTALL_PREFIX/lib/nsogcd/gc_controller/ble/sw2_protocol.py"

    cat > "$INSTALL_PREFIX/bin/nsogcd" <<WRAPPER
#!/usr/bin/env bash
exec "$INSTALL_PREFIX/lib/nsogcd/.venv/bin/python" "$INSTALL_PREFIX/lib/nsogcd/nsogcd.py" "\$@"
WRAPPER
    chmod 755 "$INSTALL_PREFIX/bin/nsogcd"

    # systemd service
    cat > /etc/systemd/system/nsogcd.service <<UNIT
[Unit]
Description=NSO GameCube Controller Daemon
Documentation=https://github.com/loserkidsblink/nsogcd
After=bluetooth.service

[Service]
Type=simple
User=root
ExecStartPre=/usr/bin/systemctl mask --runtime --now bluetooth.service
ExecStart=$INSTALL_PREFIX/bin/nsogcd
ExecStopPost=-/usr/bin/systemctl unmask --runtime bluetooth.service
ExecStopPost=-/usr/bin/systemctl --no-block start bluetooth.service
Restart=on-failure
RestartSec=10
TimeoutStartSec=300
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
UNIT
    chmod 644 /etc/systemd/system/nsogcd.service

    systemctl daemon-reload
    echo "Files installed to $INSTALL_PREFIX/."
}

enable_service() {
    echo "Enabling and starting nsogcd..."
    systemctl enable nsogcd >/dev/null 2>&1 || true
    systemctl reset-failed nsogcd 2>/dev/null || true
    systemctl restart nsogcd || {
        echo "Warning: failed to start nsogcd. Check 'journalctl -u nsogcd' for details."
        return 1
    }
    sleep 2
    if systemctl is-active nsogcd >/dev/null 2>&1; then
        echo "nsogcd is running."
    else
        echo "Warning: nsogcd not active. Check 'journalctl -u nsogcd'."
    fi
}

cleanup() {
    if [ "${SRC_DIR_TEMP:-0}" -eq 1 ] && [ -n "${SRC_DIR:-}" ] && [ -d "$SRC_DIR" ]; then
        rm -rf "$SRC_DIR"
    fi
}
trap cleanup EXIT

install_deps
fetch_source
install_files
enable_service
if [ -t 1 ]; then
    echo "Hold Sync on the NSO GameCube controller until its LEDs sweep."
    if ! "$INSTALL_PREFIX/bin/nsogcd" pair --wait; then
        echo "Pairing can be retried later with: sudo nsogcd pair --wait"
    fi
else
    "$INSTALL_PREFIX/bin/nsogcd" pair
fi

echo
echo "=================================================="
echo "  Installation complete!"
echo "=================================================="
echo
echo "For first-time pairing or retry: sudo nsogcd pair --wait"
echo
echo "To check daemon status:    systemctl status nsogcd"
echo "To check controller:       nsogcd status"
echo "To watch live logs:        journalctl -u nsogcd -f"
echo "To stop daemon:            sudo systemctl stop nsogcd"
echo "To uninstall:              see the README's Uninstall section"
echo
echo "If using with Dolphin/RetroArch/Project+, also disable Steam Input"
echo "for those games (Steam → game properties → Controller → Disable Steam Input)."
