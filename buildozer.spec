[app]

# Application name
title = Hermes Mobile

# Package name
package.name = hermesmobile
package.domain = com.hermes.mobile

# Source directory
source.dir = .

# Source files to include
source.include_exts = py,png,jpg,kv,atlas,json,txt,md,yaml,yml,svg

# Version
version = 0.1.0

# Requirements
requirements = python3,flet,openai,httpx,pydantic,pydantic-settings,python-dotenv,sqlite-utils,aiofiles,pyyaml,rich,tenacity,tiktoken,markdown,beautifulsoup4,lxml,cryptography,keyring,platformdirs,watchdog,apscheduler,plyer

# Android specific
android.permissions = INTERNET,ACCESS_NETWORK_STATE,FOREGROUND_SERVICE,FOREGROUND_SERVICE_DATA_SYNC,RECEIVE_BOOT_COMPLETED,WAKE_LOCK,VIBRATE,POST_NOTIFICATIONS
android.api = 34
android.minapi = 24
android.ndk = 25c
android.gradle_dependencies = androidx.appcompat:appcompat:1.6.1,com.google.android.material:material:1.11.0
android.enable_androidx = True
android.allow_backup = True

# Icon and splash
icon.filename = assets/icon.png
presplash.filename = assets/splash.png

# Orientation
orientation = portrait

# Fullscreen
fullscreen = 0

# Log level
log_level = 2

# Warn on root
warn_on_root = 0

# Build
build_dir = .buildozer
dist_dir = dist

# Exclude patterns
exclude_patterns = venv,__pycache__,*.pyc,.git,.github,tests,docs,*.md,*.txt,*.rst

# Python optimization
python.optimize = 2

# Android specific build options
android.gradle_dependencies += com.google.firebase:firebase-messaging:23.4.0
[buildozer]
warn_on_root = 0
