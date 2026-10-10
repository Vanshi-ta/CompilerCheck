// compilercheck: category=boundary safety=well_defined expect_exit=0
#include <limits.h>
#include <stdio.h>

int main(void) {
    unsigned u = UINT_MAX;
    u += 2u;
    int m = INT_MAX - 1;
    printf("%u\n%d\n%d\n", u, m, INT_MIN + 1);
    return 0;
}
