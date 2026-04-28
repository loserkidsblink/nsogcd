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
            # Fedora/RHEL family. Bazzite is OSTree-immutable but pip --user works in /var/home.
            if ! command -v python3 >/dev/null; then echo "ERROR: python3 not found"; exit 1; fi
            if command -v rpm-ostree >/dev/null && [ -f /run/ostree-booted ]; then
                echo "OSTree-based system detected. Installing Python deps via pip --user."
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
            apt-get install -y python3-pip bluez 2>/dev/null || true
            ;;
        *)
            echo "Warning: unrecognized distro '$OS_ID'. Assuming Python and bluez are available."
            ;;
    esac

    # Install Python deps via pip
    INVOKE_USER="${SUDO_USER:-root}"
    USER_HOME=$(getent passwd "$INVOKE_USER" | cut -d: -f6)
    sudo -u "$INVOKE_USER" python3 -m pip install --user --quiet \
        bumble evdev pyusb \
        || python3 -m pip install --break-system-packages --quiet bumble evdev pyusb \
        || { echo "ERROR: failed to install Python dependencies"; exit 1; }

    echo "Dependencies installed."
}

# Clone or update the repo to a temp location
fetch_source() {
    SRC_DIR=$(mktemp -d)
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

    install -d -m 755 "$INSTALL_PREFIX/lib/nsogcd"
    install -m 755 "$SRC_DIR/daemon/nsogcd.py" "$INSTALL_PREFIX/lib/nsogcd/nsogcd.py"

    # Install a wrapper that invokes Python with the right PYTHONPATH
    INVOKE_USER="${SUDO_USER:-root}"
    USER_HOME=$(getent passwd "$INVOKE_USER" | cut -d: -f6)

    cat > "$INSTALL_PREFIX/bin/nsogcd" <<WRAPPER
#!/usr/bin/env bash
export PYTHONPATH="\${PYTHONPATH:+\$PYTHONPATH:}$USER_HOME/.local/lib/python3.14/site-packages:$USER_HOME/.local/lib/python3.13/site-packages:$USER_HOME/.local/lib/python3.12/site-packages:$USER_HOME/.local/lib/python3.11/site-packages"
exec /usr/bin/python3 "$INSTALL_PREFIX/lib/nsogcd/nsogcd.py" "\$@"
WRAPPER
    chmod 755 "$INSTALL_PREFIX/bin/nsogcd"

    # systemd service
    cat > /etc/systemd/system/nsogcd.service <<UNIT
[Unit]
Description=NSO GameCube Controller Daemon
Documentation=https://github.com/loserkidsblink/nsogcd
After=bluetooth.service
Conflicts=bluetooth.service

[Service]
Type=simple
User=root
ExecStartPre=-/usr/bin/systemctl stop bluetooth.service
ExecStart=$INSTALL_PREFIX/bin/nsogcd
ExecStopPost=-/usr/bin/systemctl start bluetooth.service
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
    systemctl start nsogcd || {
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
    if [ -n "${SRC_DIR:-}" ] && [ -d "$SRC_DIR" ]; then
        rm -rf "$SRC_DIR"
    fi
}
trap cleanup EXIT

install_deps
fetch_source
install_files
enable_service

echo
echo "=================================================="
echo "  Installation complete!"
echo "=================================================="
echo
echo "Press the sync button on your NSO GameCube controller now."
echo "It should pair within ~3 seconds."
echo
echo "To check daemon status:    systemctl status nsogcd"
echo "To watch live logs:        journalctl -u nsogcd -f"
echo "To stop daemon (and"
echo "  restore Bluetooth):      sudo systemctl stop nsogcd"
echo "To uninstall:              sudo $INSTALL_PREFIX/lib/nsogcd/uninstall.sh"
echo
echo "If using with Dolphin/RetroArch/Project+, also disable Steam Input"
echo "for those games (Steam → game properties → Controller → Disable Steam Input)."
