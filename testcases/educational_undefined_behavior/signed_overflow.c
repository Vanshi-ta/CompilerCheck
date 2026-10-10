// compilercheck: category=undefined_behavior safety=undefined_behavior description="signed overflow: x + 1 > x"
// Signed integer overflow is undefined in C and C++. An optimizer may assume it never
// happens and fold `x + 1 > x` to true, while -O0 typically wraps and yields false.
#include <limits.h>
#include <stdio.h>

static int always_greater(int x) {
    return x + 1 > x;
}

int main(void) {
    volatile int v = INT_MAX;
    printf("%d\n", always_greater(v));
    return 0;
}
