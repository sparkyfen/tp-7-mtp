#!/bin/bash
set -e

VERSION="${1:?Usage: build-deb.sh <version> [codename]}"
CODENAME="${2:-noble}"  # Default to Ubuntu 24.04
PKG="tp7-mtp"
ARCH="all"
DEB_NAME="${PKG}_${VERSION}+${CODENAME}_${ARCH}"
BUILD_DIR="build/${DEB_NAME}"

echo "Building ${DEB_NAME}.deb ..."

rm -rf "build/${DEB_NAME}"
mkdir -p "${BUILD_DIR}/DEBIAN"
mkdir -p "${BUILD_DIR}/usr/bin"
mkdir -p "${BUILD_DIR}/usr/lib/tp7-mtp"
mkdir -p "${BUILD_DIR}/etc/udev/rules.d"
mkdir -p "${BUILD_DIR}/usr/share/applications"
mkdir -p "${BUILD_DIR}/usr/share/icons/hicolor/256x256/apps"

# Control file
sed "s/VERSION_PLACEHOLDER/${VERSION}+${CODENAME}/" debian/control > "${BUILD_DIR}/DEBIAN/control"

# Post-install script
cp debian/postinst "${BUILD_DIR}/DEBIAN/postinst"
chmod 755 "${BUILD_DIR}/DEBIAN/postinst"

# Application files
cp tp7_linux.py "${BUILD_DIR}/usr/lib/tp7-mtp/"
cp tp7_files.py "${BUILD_DIR}/usr/lib/tp7-mtp/"
cp tp7_tray.py  "${BUILD_DIR}/usr/lib/tp7-mtp/"
cp icon_active.png "${BUILD_DIR}/usr/lib/tp7-mtp/"
cp icon_dim.png "${BUILD_DIR}/usr/lib/tp7-mtp/"

# Wrapper scripts
cat > "${BUILD_DIR}/usr/bin/tp7-tray" << 'EOF'
#!/bin/sh
exec python3 /usr/lib/tp7-mtp/tp7_tray.py "$@"
EOF
chmod 755 "${BUILD_DIR}/usr/bin/tp7-tray"

cat > "${BUILD_DIR}/usr/bin/tp7-mtp" << 'EOF'
#!/bin/sh
exec python3 /usr/lib/tp7-mtp/tp7_linux.py "$@"
EOF
chmod 755 "${BUILD_DIR}/usr/bin/tp7-mtp"

cat > "${BUILD_DIR}/usr/bin/tp7-files" << 'EOF'
#!/bin/sh
exec python3 /usr/lib/tp7-mtp/tp7_files.py "$@"
EOF
chmod 755 "${BUILD_DIR}/usr/bin/tp7-files"

# udev rules
cp 69-teenage-engineering.rules "${BUILD_DIR}/etc/udev/rules.d/"

# Desktop entry
cp debian/tp7-mtp.desktop "${BUILD_DIR}/usr/share/applications/"

# Icon
cp icon_256.png "${BUILD_DIR}/usr/share/icons/hicolor/256x256/apps/tp7-mtp.png"

# Build the deb
dpkg-deb --build "${BUILD_DIR}"
echo "Built: build/${DEB_NAME}.deb"
