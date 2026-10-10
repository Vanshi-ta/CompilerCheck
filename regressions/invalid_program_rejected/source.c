// compilercheck: category=general safety=invalid description="intentionally invalid program"
// Intentionally ill-formed: expected outcome is COMPILE_ERROR under every configuration.
#include <stdio.h>

int main(void) {
    printf("never compiled\n")
    return 0;
}
