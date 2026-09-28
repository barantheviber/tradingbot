// JVM test for the phone's restart rules (../shared/RunMemory.kt), without the Android SDK:
//   gradle -p mobile/plugins/bot-runtime/jvm-test test
plugins {
  kotlin("jvm") version "2.1.20"
}

repositories {
  mavenCentral()
}

dependencies {
  testImplementation(kotlin("test"))
}

sourceSets {
  main { kotlin.srcDir("../shared") }
}

tasks.test {
  useJUnitPlatform()
  testLogging { events("passed", "failed") }
}
