#include <mach-o/dyld.h>
#include <limits.h>
#include <libgen.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    uint32_t size = PATH_MAX;
    char exe_path[PATH_MAX];
    if (_NSGetExecutablePath(exe_path, &size) != 0) {
        fprintf(stderr, "MCPtoAI Device Agent launcher: executable path too long\n");
        return 127;
    }
    char resolved[PATH_MAX];
    if (!realpath(exe_path, resolved)) {
        perror("MCPtoAI Device Agent launcher realpath");
        return 127;
    }

    char macos_dir[PATH_MAX];
    strlcpy(macos_dir, resolved, sizeof(macos_dir));
    char *contents_dir = dirname(macos_dir);
    contents_dir = dirname(contents_dir);

    char agent_path[PATH_MAX];
    if (snprintf(agent_path, sizeof(agent_path), "%s/Resources/agent/mcptoai-agent", contents_dir) >= (int)sizeof(agent_path)) {
        fprintf(stderr, "MCPtoAI Device Agent launcher: agent path too long\n");
        return 127;
    }

    int child_argc = argc == 1 ? 2 : argc;
    char **child_argv = calloc((size_t)child_argc + 1, sizeof(char *));
    if (!child_argv) return 127;
    child_argv[0] = agent_path;
    if (argc == 1) {
        child_argv[1] = "connect";
    } else {
        for (int i = 1; i < argc; i++) child_argv[i] = argv[i];
    }
    child_argv[child_argc] = NULL;

    execv(agent_path, child_argv);
    perror("MCPtoAI Device Agent launcher execv");
    free(child_argv);
    return 127;
}
