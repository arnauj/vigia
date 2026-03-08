; VIGIA Server Installer — NSIS script
; Generated from Linux using makensis

Unicode True

!define APP_NAME      "VIGIA Server"
!define APP_EXE       "VIGIA-Server.exe"
!define APP_ID        "vigia-server"
!define APP_VERSION   "1.1"
!define PUBLISHER     "VIGIA"
!define INSTALL_DIR   "$PROGRAMFILES64\VIGIA Server"

; --- Compression ---
SetCompressor /SOLID lzma

; --- General ---
Name "${APP_NAME} ${APP_VERSION}"
OutFile "/home/user/vigia/dist/windows/installers/vigia-server-${APP_VERSION}-setup.exe"
InstallDir "${INSTALL_DIR}"
InstallDirRegKey HKLM "Software\${APP_ID}" "InstallDir"
RequestExecutionLevel admin
ShowInstDetails show
ShowUninstDetails show

; --- Pages ---
!include "MUI2.nsh"
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Spanish"

; --- Installation ---
Section "Principal" SecMain
    SectionIn RO
    SetOutPath "$INSTDIR"
    File /r "/home/user/vigia/dist/windows/bin/VIGIA-Server/*.*"

    ; Registry
    WriteRegStr HKLM "Software\${APP_ID}" "InstallDir" "$INSTDIR"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" \
        "DisplayName" "${APP_NAME}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" \
        "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" \
        "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" \
        "Publisher" "${PUBLISHER}"

    ; Shortcuts
    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
    CreateShortcut "$SMPROGRAMS\${APP_NAME}\Desinstalar.lnk" "$INSTDIR\uninstall.exe"
    CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"

    WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

; --- Uninstall ---
Section "Uninstall"
    RMDir /r "$INSTDIR"
    Delete "$DESKTOP\${APP_NAME}.lnk"
    RMDir /r "$SMPROGRAMS\${APP_NAME}"
    DeleteRegKey HKLM "Software\${APP_ID}"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}"
SectionEnd
