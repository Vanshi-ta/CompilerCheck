// compilercheck: category=undefined_behavior safety=undefined_behavior description="pointer to a dead local"
// Using a pointer to an object whose lifetime ended is an invalid pointer operation.
#include <stdio.h>

static int *escape(void) {
    int local = 42;
    return &local;
}

int main(void) {
    int *p = escape();
    printf("%d\n", *p);
    return 0;
}
