@echo off

set DIRNAME=%~dp0
if "%DIRNAME%" == "" set DIRNAME=.
set APP_HOME=%DIRNAME%

set CLASSPATH=%APP_HOME%\gradle\wrapper\gradle-wrapper.jar

if defined JAVA_HOME set JAVACMD=%JAVA_HOME%\bin\java.exe
if not defined JAVACMD set JAVACMD=java.exe

"%JAVACMD%" -Dorg.gradle.appname=gradlew -classpath "%CLASSPATH%" org.gradle.wrapper.GradleWrapperMain %*
