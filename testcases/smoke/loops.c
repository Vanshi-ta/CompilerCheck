// compilercheck: category=loops_conditionals safety=well_defined expect_exit=0
#include <stdio.h>

int main(void) {
    int sum = 0;
    for (int i = 1; i <= 100; ++i) {
        if (i % 3 == 0 || i % 5 == 0) {
            sum += i;
        }
    }
    int n = 27, steps = 0;
    while (n != 1) {
        n = (n % 2 == 0) ? n / 2 : 3 * n + 1;
        ++steps;
    }
    printf("%d\n%d\n", sum, steps);
    return 0;
}
