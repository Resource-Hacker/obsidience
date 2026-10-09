#!/usr/bin/env bash
# Build the Obsidience TV agent (org.obsidience.tv) without Gradle: aapt2 + javac + d8 + apksigner.
#   SDK platform : /opt/android-sdk/platforms/android-35/android.jar (override ANDROID_JAR)
#   build-tools  : ~/Android/Sdk/build-tools/36.0.0 (override BT)
# The signing keystore is private to this installation and never enters the repository:
# ~/.local/share/obsidience/tv-agent.keystore, generated on first build. Its password is
# not a secret; the file's owner-only permissions protect the key. Keep the keystore: an
# update installs over the existing app only with the same signing key.
# Output: obsidience/state/tv-agent/obsidience-tv-<versionCode>.apk (ignored installation state).
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SRC/../../.." && pwd)"
BT="${BT:-$HOME/Android/Sdk/build-tools/36.0.0}"
ANDROID_JAR="${ANDROID_JAR:-/opt/android-sdk/platforms/android-35/android.jar}"
KEYDIR="$HOME/.local/share/obsidience"
KS="$KEYDIR/tv-agent.keystore"
PASS=obsidience-tv-agent
DIST="$REPO/obsidience/state/tv-agent"
VERSION="$(grep -oP 'android:versionCode="\K[0-9]+' "$SRC/AndroidManifest.xml")"
APK="$DIST/obsidience-tv-$VERSION.apk"

OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex" "$DIST"

"$BT/aapt2" compile --dir "$SRC/res" -o "$OUT/res.zip"
"$BT/aapt2" link -o "$OUT/base.apk" -I "$ANDROID_JAR" --manifest "$SRC/AndroidManifest.xml" \
    --java "$OUT/gen" --min-sdk-version 30 --target-sdk-version 30 "$OUT/res.zip"
find "$SRC/src" "$OUT/gen" -name '*.java' > "$OUT/sources.txt"
javac -d "$OUT/classes" -classpath "$ANDROID_JAR" -source 8 -target 8 -Xlint:-options -Xlint:deprecation \
    @"$OUT/sources.txt"
mapfile -t CLASSES < <(find "$OUT/classes" -name '*.class')
"$BT/d8" --min-api 30 --lib "$ANDROID_JAR" --output "$OUT/dex" "${CLASSES[@]}"
cp "$OUT/base.apk" "$OUT/unsigned.apk"
( cd "$OUT/dex" && zip -q "$OUT/unsigned.apk" classes.dex )
"$BT/zipalign" -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"

if [ ! -f "$KS" ]; then
    install -d -m 700 "$KEYDIR"
    ( umask 077 && keytool -genkeypair -keystore "$KS" -storetype PKCS12 -storepass "$PASS" -keypass "$PASS" \
        -alias obsidience-tv -keyalg RSA -keysize 3072 -validity 36500 \
        -dname "CN=Obsidience TV agent" >/dev/null 2>&1 )
fi
"$BT/apksigner" sign --ks "$KS" --ks-pass "pass:$PASS" --key-pass "pass:$PASS" --out "$APK" "$OUT/aligned.apk"
"$BT/apksigner" verify "$APK"
echo "$APK"
