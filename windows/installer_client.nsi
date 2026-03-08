; VIGIA Client Installer — NSIS script
; Generated from Linux using makensis

Unicode True

!define APP_NAME      "VIGIA Client"
!define APP_EXE       "VIGIA-Client.exe"
!define APP_ID        "vigia-client"
!define APP_VERSION   "1.1"
!define PUBLISHER     "VIGIA"
!define INSTALL_DIR   "$PROGRAMFILES64\VIGIA Client"

SetCompressor /SOLID lzma

Name "${APP_NAME} ${APP_VERSION}"
OutFile "/home/user/vigia/dist/windows/installers/vigia-client-${APP_VERSION}-setup.exe"
InstallDir "${INSTALL_DIR}"
InstallDirRegKey HKLM "Software\${APP_ID}" "InstallDir"
RequestExecutionLevel admin
ShowInstDetails show
ShowUninstDetails show

; --- Pages ---
!include "MUI2.nsh"
Var ServerIP

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
Page custom ServerIPPage ServerIPPageLeave
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Spanish"

; --- Custom page: Server IP ---
!include "nsDialogs.nsh"
!include "LogicLib.nsh"

Var Dialog
Var LabelIP
Var TextIP

Function ServerIPPage
    nsDialogs::Create 1018
    Pop $Dialog
    ${If} $Dialog == error
        Abort
    ${EndIf}

    ${NSD_CreateLabel} 0 0 100% 24u "Introduce la IP del equipo del profesor (servidor VIGIA):"
    Pop $LabelIP

    ${NSD_CreateText} 0 28u 100% 14u "192.168.1.2"
    Pop $TextIP

    nsDialogs::Show
FunctionEnd

Function ServerIPPageLeave
    ${NSD_GetText} $TextIP $ServerIP
    StrCmp $ServerIP "" 0 +3
        MessageBox MB_OK|MB_ICONEXCLAMATION "Por favor, introduce la IP del servidor."
        Abort
FunctionEnd

; --- Installation ---
Section "Principal" SecMain
    SectionIn RO
    SetOutPath "$INSTDIR"
    File /r "/home/user/vigia/dist/windows/bin/VIGIA-Client/*.*"

    ; Save server IP to ProgramData\VIGIA\client.conf
    CreateDirectory "$COMMONPROGRAMDATA\VIGIA"
    FileOpen $0 "$COMMONPROGRAMDATA\VIGIA\client.conf" w
    FileWrite $0 "$ServerIP$\r$\n"
    FileClose $0

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

    ; Autostart (run on Windows login)
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Run" \
        "${APP_NAME}" "$INSTDIR\${APP_EXE}"

    WriteUninstaller "$INSTDIR\uninstall.exe"

    ; Launch immediately
    Exec "$INSTDIR\${APP_EXE}"
SectionEnd

; --- Uninstall ---
Section "Uninstall"
    DeleteRegValue HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "${APP_NAME}"
    RMDir /r "$INSTDIR"
    Delete "$DESKTOP\${APP_NAME}.lnk"
    RMDir /r "$SMPROGRAMS\${APP_NAME}"
    DeleteRegKey HKLM "Software\${APP_ID}"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}"
SectionEnd
