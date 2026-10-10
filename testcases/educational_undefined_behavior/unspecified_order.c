// compilercheck: category=undefined_behavior safety=undefined_behavior description="unspecified evaluation order"
// The order in which function arguments are evaluated is unspecified. Different compilers
// (and sometimes flags) pick different orders; both are conforming.
#include <stdio.h>

static int first(void)  { printf("first\n");  return 1; }
static int second(void) { printf("second\n"); return 2; }

static int combine(int a, int b) { return a * 10 + b; }

int main(void) {
    printf("%d\n", combine(first(), second()));
    return 0;
}
