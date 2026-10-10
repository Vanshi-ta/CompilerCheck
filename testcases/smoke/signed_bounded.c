// compilercheck: category=signed_unsigned safety=well_defined expect_exit=0
#include <stdio.h>

int main(void) {
    int a = -17, b = 5;
    printf("%d %d\n", a / b, a % b);   /* C99/C++11: truncation toward zero */
    printf("%d\n", a * b + 100);
    return 0;
}
