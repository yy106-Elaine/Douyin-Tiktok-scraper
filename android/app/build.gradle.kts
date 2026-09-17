plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.devtools.ksp")
}

android {
    namespace = "edu.wellesley.scraper"
    compileSdk = 35

    defaultConfig {
        applicationId = "edu.wellesley.scraper"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"

        // Override per build with -PbackendBaseUrl=... or edit here.
        buildConfigField(
            "String",
            "DEFAULT_BACKEND_URL",
            "\"${project.findProperty("backendBaseUrl") ?: "https://example.invalid"}\"",
        )
    }

    // A checked-in debug key, so every CI build signs identically.
    // Without it the runner generates a throwaway key per build and each
    // new APK refuses to install over the last one
    // (INSTALL_FAILED_UPDATE_INCOMPATIBLE), which makes "download the
    // latest build and reinstall" impossible. Debug keys are not secrets:
    // Android's own default debug key has published credentials, and this
    // one signs nothing that is distributed.
    signingConfigs {
        getByName("debug") {
            storeFile = file("debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }

    buildFeatures {
        buildConfig = true
        viewBinding = true
    }

    buildTypes {
        debug {
            signingConfig = signingConfigs.getByName("debug")
        }
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }

    // The parsers touch only AccessibilityNodeInfo's flattened output, so
    // their logic is testable on the JVM without a device.
    testOptions { unitTests.isReturnDefaultValues = true }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    // ComponentActivity and lifecycleScope, used by the translucent
    // clipboard reader, which cannot take an AppCompat theme.
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.2.0")

    implementation("androidx.room:room-runtime:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")
    ksp("androidx.room:room-compiler:2.6.1")

    implementation("androidx.work:work-runtime-ktx:2.10.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    testImplementation("junit:junit:4.13.2")
}
