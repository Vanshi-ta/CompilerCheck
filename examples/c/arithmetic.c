// compilercheck: category=integer_arithmetic safety=well_defined expect_exit=0
#include <stdio.h>
#include <stdint.h>

int main(void) {
    uint32_t h = 2166136261u;           /* FNV-1a over a short string */
    const char *s = "compilercheck";
    for (int i = 0; s[i] != '\0'; ++i) {
        h ^= (uint32_t)(unsigned char)s[i];
        h *= 16777619u;
    }
    printf("%u\n", h);
    return 0;
}
