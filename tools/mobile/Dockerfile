# Keep the Flutter compiler and Android SDK inputs immutable. The image and
# digest are supplied from versions.env by mobile-image.
ARG MOBILE_FLUTTER_IMAGE
ARG MOBILE_FLUTTER_IMAGE_DIGEST
FROM ${MOBILE_FLUTTER_IMAGE}@${MOBILE_FLUTTER_IMAGE_DIGEST}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG MOBILE_FLUTTER_IMAGE
ARG MOBILE_FLUTTER_IMAGE_DIGEST
ARG MOBILE_FLUTTER_VERSION
ARG MOBILE_ANDROID_SDK_TOOLS_VERSION
ARG MOBILE_ANDROID_CMDLINE_TOOLS_REVISION
ARG MOBILE_ANDROID_PLATFORM_TOOLS_VERSION
ARG MOBILE_ANDROID_PLATFORM_VERSION
ARG MOBILE_ANDROID_BUILD_TOOLS_VERSION
ARG MOBILE_ANDROID_AGP_BUILD_TOOLS_VERSION
ARG MOBILE_ANDROID_NDK_VERSION
ARG MOBILE_JAVA_MAJOR_VERSION
ARG MOBILE_GRADLE_VERSION
ARG MOBILE_ANDROID_GRADLE_PLUGIN_VERSION
ARG MOBILE_KOTLIN_VERSION

COPY versions.env /tmp/mobile-versions.env

ENV ANDROID_HOME=/opt/android-sdk-linux \
    ANDROID_SDK_ROOT=/opt/android-sdk-linux \
    FLUTTER_HOME=/sdks/flutter \
    FLUTTER_ROOT=/sdks/flutter

USER root

RUN apt-get update \
    && apt-get install --no-install-recommends --yes \
        ca-certificates \
        curl \
        git \
        openjdk-17-jdk-headless \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# Keep JAVA_HOME stable across architectures. The package directory has an
# architecture suffix, so resolve it after installing the JDK.
RUN set -eux; \
    java_home=$(dirname "$(dirname "$(readlink -f "$(command -v java)")")"); \
    ln -sfn "$java_home" /opt/java-home

ENV JAVA_HOME=/opt/java-home
ENV PATH=/sdks/flutter/bin:/sdks/flutter/bin/cache/dart-sdk/bin:/opt/android-sdk-linux/cmdline-tools/latest/bin:/opt/android-sdk-linux/platform-tools:/opt/android-sdk-linux/emulator:$JAVA_HOME/bin:$PATH

RUN set -eux; \
    source /tmp/mobile-versions.env; \
    test "$MOBILE_FLUTTER_IMAGE" = "$FLUTTER_IMAGE"; \
    test "$MOBILE_FLUTTER_IMAGE_DIGEST" = "$FLUTTER_IMAGE_DIGEST"; \
    test "$MOBILE_FLUTTER_VERSION" = "$FLUTTER_VERSION"; \
    test "$MOBILE_ANDROID_SDK_TOOLS_VERSION" = "$ANDROID_SDK_TOOLS_VERSION"; \
    test "$MOBILE_ANDROID_CMDLINE_TOOLS_REVISION" = "$ANDROID_CMDLINE_TOOLS_REVISION"; \
    test "$MOBILE_ANDROID_PLATFORM_TOOLS_VERSION" = "$ANDROID_PLATFORM_TOOLS_VERSION"; \
    test "$MOBILE_ANDROID_PLATFORM_VERSION" = "$ANDROID_PLATFORM_VERSION"; \
    test "$MOBILE_ANDROID_BUILD_TOOLS_VERSION" = "$ANDROID_BUILD_TOOLS_VERSION"; \
    test "$MOBILE_ANDROID_AGP_BUILD_TOOLS_VERSION" = "$ANDROID_AGP_BUILD_TOOLS_VERSION"; \
    test "$MOBILE_ANDROID_NDK_VERSION" = "$ANDROID_NDK_VERSION"; \
    test "$MOBILE_JAVA_MAJOR_VERSION" = "$JAVA_MAJOR_VERSION"; \
    test "$MOBILE_GRADLE_VERSION" = "$GRADLE_VERSION"; \
    test "$MOBILE_ANDROID_GRADLE_PLUGIN_VERSION" = "$ANDROID_GRADLE_PLUGIN_VERSION"; \
    test "$MOBILE_KOTLIN_VERSION" = "$KOTLIN_VERSION"; \
    test "${ANDROID_SDK_TOOLS_VERSION:-}" = "$MOBILE_ANDROID_SDK_TOOLS_VERSION"; \
    test -x "${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager"; \
    cmdline_tools_revision=$(sed -n 's/^Pkg.Revision[[:space:]]*=[[:space:]]*//p' "${ANDROID_HOME}/cmdline-tools/latest/source.properties"); \
    test "$cmdline_tools_revision" = "$MOBILE_ANDROID_CMDLINE_TOOLS_REVISION"; \
    set +e; \
    yes | sdkmanager --licenses >/dev/null; \
    license_status=${PIPESTATUS[1]}; \
    set -e; \
    test "$license_status" -eq 0; \
    sdkmanager \
        "platforms;android-${ANDROID_PLATFORM_VERSION}" \
        "build-tools;${ANDROID_BUILD_TOOLS_VERSION}" \
        "build-tools;${ANDROID_AGP_BUILD_TOOLS_VERSION}" \
        "ndk;${ANDROID_NDK_VERSION}"; \
    platform_tools_revision=$(sed -n 's/^Pkg.Revision[[:space:]]*=[[:space:]]*//p' "${ANDROID_HOME}/platform-tools/source.properties"); \
    test "$platform_tools_revision" = "$MOBILE_ANDROID_PLATFORM_TOOLS_VERSION"; \
    platform_api=$(sed -n 's/^AndroidVersion.ApiLevel[[:space:]]*=[[:space:]]*//p' "${ANDROID_HOME}/platforms/android-${ANDROID_PLATFORM_VERSION}/source.properties"); \
    test "$platform_api" = "$MOBILE_ANDROID_PLATFORM_VERSION"; \
    build_tools_revision=$(sed -n 's/^Pkg.Revision[[:space:]]*=[[:space:]]*//p' "${ANDROID_HOME}/build-tools/${ANDROID_BUILD_TOOLS_VERSION}/source.properties"); \
    test "$build_tools_revision" = "$MOBILE_ANDROID_BUILD_TOOLS_VERSION"; \
    agp_build_tools_revision=$(sed -n 's/^Pkg.Revision[[:space:]]*=[[:space:]]*//p' "${ANDROID_HOME}/build-tools/${ANDROID_AGP_BUILD_TOOLS_VERSION}/source.properties"); \
    test "$agp_build_tools_revision" = "$MOBILE_ANDROID_AGP_BUILD_TOOLS_VERSION"; \
    ndk_revision=$(sed -n 's/^Pkg.Revision[[:space:]]*=[[:space:]]*//p' "${ANDROID_HOME}/ndk/${ANDROID_NDK_VERSION}/source.properties"); \
    test "$ndk_revision" = "$MOBILE_ANDROID_NDK_VERSION"; \
    java_major=$(java -version 2>&1 | sed -n 's/.*version "\([0-9]*\).*/\1/p'); \
    test "$java_major" = "$MOBILE_JAVA_MAJOR_VERSION"; \
    flutter config --no-analytics; \
    flutter precache --android; \
    git config --system --add safe.directory /sdks/flutter; \
    chmod -R a+rwX /sdks/flutter/bin/cache; \
    chmod -R a+rwX /sdks/flutter/packages/flutter_tools; \
    chmod a+rw /sdks/flutter/version; \
    chmod -R a+rX /opt/android-sdk-linux

RUN set -eux; \
    source /tmp/mobile-versions.env; \
    mkdir -p /opt/gradle; \
    curl --fail --silent --show-error --location \
        "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" \
        --output /tmp/gradle.zip; \
    unzip -q /tmp/gradle.zip -d /opt/gradle; \
    ln -sfn "/opt/gradle/gradle-${GRADLE_VERSION}" /opt/gradle/current; \
    rm /tmp/gradle.zip

ENV GRADLE_HOME=/opt/gradle/current
ENV PATH=$GRADLE_HOME/bin:$PATH

# Keep image metadata useful when an image is inspected without a project mount.
RUN set -eux; \
    source /tmp/mobile-versions.env; \
    flutter --version; \
    dart --version; \
    java -version; \
    sdkmanager --version; \
    adb version; \
    gradle_version=$(gradle --version | sed -n 's/^Gradle \([^[:space:]]*\).*/\1/p' | head -n 1); \
    test "$gradle_version" = "$GRADLE_VERSION"

WORKDIR /workspace/client/mobile
CMD ["/bin/bash"]
