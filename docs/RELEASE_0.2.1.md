# nsogcd v0.2.1

This release adds an installable Linux bundle to v0.2.0. Download **`nsogcd-v0.2.1-linux.tar.gz`** from this page. It contains the daemon, pairing backend, and installer, so you do not need Git or a separate pairing-app checkout.

```bash
tar -xzf nsogcd-v0.2.1-linux.tar.gz
cd nsogcd-v0.2.1-linux
sudo ./install.sh
```

The installer uses the files in the extracted bundle instead of cloning the repository again. It still downloads Python dependencies into a dedicated virtual environment on the target machine. A SHA-256 file is attached alongside the bundle.

Controller behavior is unchanged from v0.2.0: explicit first pairing, button-wake reconnect, bundled BLE backend, Z/ZL and analog input, and native GameCube motor on/off timing. These paths were exercised on a Bazzite Legion Go. Fresh installation on other distributions and SteamOS remains unverified. The service still takes control of its Bluetooth adapter while running; see the README for the full limits and Linux/Mac alternatives.
