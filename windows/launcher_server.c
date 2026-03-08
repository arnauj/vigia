/*
 * VIGIA Server Launcher
 * Launches pythonw.exe from the bundled python\ directory with server.py
 */
#include <windows.h>
#include <stdio.h>

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance,
                   LPSTR lpCmdLine, int nCmdShow)
{
    char exeDir[MAX_PATH];
    char pythonExe[MAX_PATH];
    char scriptPath[MAX_PATH];
    char cmdLine[MAX_PATH * 2 + 32];

    GetModuleFileNameA(NULL, exeDir, MAX_PATH);
    /* strip filename to get directory */
    char *slash = strrchr(exeDir, '\\');
    if (slash) *slash = '\0';

    snprintf(pythonExe, sizeof(pythonExe), "%s\\python\\pythonw.exe", exeDir);
    snprintf(scriptPath, sizeof(scriptPath), "%s\\server.py", exeDir);
    snprintf(cmdLine, sizeof(cmdLine), "\"%s\" \"%s\"", pythonExe, scriptPath);

    STARTUPINFOA si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    if (!CreateProcessA(NULL, cmdLine, NULL, NULL, FALSE, 0, NULL, exeDir, &si, &pi)) {
        char msg[512];
        snprintf(msg, sizeof(msg),
            "No se pudo iniciar VIGIA Server.\n\nComando: %s\nError: %lu",
            cmdLine, GetLastError());
        MessageBoxA(NULL, msg, "VIGIA Server - Error", MB_OK | MB_ICONERROR);
        return 1;
    }

    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return 0;
}
