// compilercheck: category=arrays safety=well_defined expect_exit=0
#include <stdio.h>

int main(void) {
    int a[8];
    for (int i = 0; i < 8; ++i) {
        a[i] = i * i;
    }
    int total = 0;
    for (int i = 0; i < 8; ++i) {
        total += a[7 - i] - a[i];
    }
    printf("%d %d %d\n", a[3], a[7], total);
    return 0;
}
