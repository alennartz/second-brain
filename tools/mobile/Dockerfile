# Keep the Flutter compiler and Android SDK inputs immutable.
FROM ghcr.io/cirruslabs/flutter:3.22.3@sha256:9a11eb88b86557a132008cceb551dbb82b6df147f556da45a154768bd5156bc8

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY versions.env /tmp/mobile-versions.env

ENV ANDROID_HOME=/opt/android-sdk-linux \
    ANDROID_SDK_ROOT=/opt/android-sdk-linux \
    FLUTTER_HOME=/sdks/flutter \
    FLUTTER_ROOT=/sdks/flutter \
    JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
    PATH=/sdks/flutter/bin:/sdks/flutter/bin/cache/dart-sdk/bin:/opt/android-sdk-linux/cmdline-tools/latest/bin:/opt/android-sdk-linux/platform-tools:/opt/android-sdk-linux/emulator:$JAVA_HOME/bin:$PATH

USER root

RUN apt-get update \
    && apt-get install --no-install-recommends --yes \
        ca-certificates \
        curl \
        git \
        openjdk-17-jdk-headless \
        unzip \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    source /tmp/mobile-versions.env; \
    test "${FLUTTER_VERSION}" = "3.22.3"; \
    test "${ANDROID_SDK_TOOLS_VERSION:-}" = "${ANDROID_CMDLINE_TOOLS_VERSION}"; \
    test -x "${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager"; \
    yes | sdkmanager --licenses >/dev/null || true; \
    sdkmanager \
        "platform-tools" \
        "platforms;android-${ANDROID_PLATFORM_VERSION}" \
        "build-tools;${ANDROID_BUILD_TOOLS_VERSION}" \
        "build-tools;${ANDROID_AGP_BUILD_TOOLS_VERSION}" \
        "ndk;${ANDROID_NDK_VERSION}"; \
    java_major=$(java -version 2>&1 | sed -n 's/.*version "\([0-9]*\).*/\1/p'); \
    test "${java_major}" = "${JAVA_MAJOR_VERSION}"; \
    flutter config --no-analytics; \
    flutter precache --android; \
    git config --system --add safe.directory /sdks/flutter; \
    chmod -R a+rwX /sdks/flutter/bin/cache; \
    chmod -R a+rwX /sdks/flutter/packages/flutter_tools; \
    chmod a+rw /sdks/flutter/version; \
    chmod -R a+rX /opt/android-sdk-linux

# Keep image metadata useful when an image is inspected without a project mount.
RUN set -eux; \
    flutter --version; \
    dart --version; \
    java -version; \
    sdkmanager --version; \
    adb version

WORKDIR /workspace/client/mobile
CMD ["/bin/bash"]
