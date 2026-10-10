// compilercheck: category=undefined_behavior safety=undefined_behavior description="out-of-bounds read"
// Reading past the end of an array is undefined; the value depends on stack layout,
// which optimization levels change freely.
#include <stdio.h>

int main(void) {
    int a[4] = {1, 2, 3, 4};
    volatile int idx = 6;
    printf("%d\n", a[idx]);
    return 0;
}
