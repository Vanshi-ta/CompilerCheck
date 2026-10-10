// compilercheck: category=undefined_behavior safety=undefined_behavior description="uninitialized variable"
// Reading an indeterminate value is undefined behavior for most types.
#include <stdio.h>

int main(void) {
    int x;
    if (x > 0) {
        printf("positive\n");
    } else {
        printf("not positive\n");
    }
    return 0;
}
