/*
 * VIGIA Client Launcher
 * Reads server IP from ProgramData\VIGIA\client.conf and launches client.py
 */
#include <windows.h>
#include <stdio.h>
#include <shlobj.h>

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance,
                   LPSTR lpCmdLine, int nCmdShow)
{
    char exeDir[MAX_PATH];
    char pythonExe[MAX_PATH];
    char scriptPath[MAX_PATH];
    char confPath[MAX_PATH];
    char serverIp[64] = "";
    char cmdLine[MAX_PATH * 2 + 128];

    GetModuleFileNameA(NULL, exeDir, MAX_PATH);
    char *slash = strrchr(exeDir, '\\');
    if (slash) *slash = '\0';

    snprintf(pythonExe, sizeof(pythonExe), "%s\\python\\pythonw.exe", exeDir);
    snprintf(scriptPath, sizeof(scriptPath), "%s\\client.py", exeDir);

    /* Try to read server IP from config */
    SHGetFolderPathA(NULL, CSIDL_COMMON_APPDATA, NULL, 0, confPath);
    strncat(confPath, "\\VIGIA\\client.conf", sizeof(confPath) - strlen(confPath) - 1);

    FILE *f = fopen(confPath, "r");
    if (f) {
        if (fgets(serverIp, sizeof(serverIp), f)) {
            /* strip trailing newline/whitespace */
            char *end = serverIp + strlen(serverIp) - 1;
            while (end >= serverIp && (*end == '\r' || *end == '\n' || *end == ' '))
                *end-- = '\0';
        }
        fclose(f);
    }

    if (serverIp[0])
        snprintf(cmdLine, sizeof(cmdLine), "\"%s\" \"%s\" %s", pythonExe, scriptPath, serverIp);
    else
        snprintf(cmdLine, sizeof(cmdLine), "\"%s\" \"%s\"", pythonExe, scriptPath);

    STARTUPINFOA si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    if (!CreateProcessA(NULL, cmdLine, NULL, NULL, FALSE, 0, NULL, exeDir, &si, &pi)) {
        char msg[512];
        snprintf(msg, sizeof(msg),
            "No se pudo iniciar VIGIA Client.\n\nComando: %s\nError: %lu",
            cmdLine, GetLastError());
        MessageBoxA(NULL, msg, "VIGIA Client - Error", MB_OK | MB_ICONERROR);
        return 1;
    }

    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return 0;
}
