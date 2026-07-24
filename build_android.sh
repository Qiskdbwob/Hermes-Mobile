#!/bin/bash
# Build script for Hermes Mobile Android APK

set -e

echo "🤖 Building Hermes Mobile for Android..."

# Check if buildozer is installed
if ! command -v buildozer &> /dev/null; then
    echo "📦 Installing buildozer..."
    pip3 install buildozer cython
fi

# Install system dependencies (Ubuntu/Debian)
if command -v apt-get &> /dev/null; then
    echo "📦 Installing system dependencies..."
    sudo apt-get update
    sudo apt-get install -y \
        git zip unzip openjdk-17-jdk python3-pip autoconf libtool pkg-config \
        zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev \
        automake libltdl-dev libjpeg-dev libpng-dev libwebp-dev
fi

# Build APK
echo "🔨 Building APK..."
buildozer -v android debug

# Copy APK to dist folder
if [ -f "bin/hermesmobile-0.1.0-armeabi-v7a-debug.apk" ]; then
    cp bin/hermesmobile-0.1.0-armeabi-v7a-debug.apk dist/hermes-mobile-debug.apk
    echo "✅ APK built: dist/hermes-mobile-debug.apk"
elif [ -f "bin/hermesmobile-0.1.0-arm64-v8a-debug.apk" ]; then
    cp bin/hermesmobile-0.1.0-arm64-v8a-debug.apk dist/hermes-mobile-debug.apk
    echo "✅ APK built: dist/hermes-mobile-debug.apk"
else
    echo "❌ APK not found in bin/"
    ls -la bin/
    exit 1
fi

echo "🎉 Build complete!"