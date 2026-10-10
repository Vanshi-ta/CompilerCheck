// compilercheck: category=floating_point safety=well_defined expect_exit=0 float_tolerance=1e-12
#include <stdio.h>

int main(void) {
    double x = 1.0;
    for (int i = 0; i < 10; ++i) {
        x = x * 0.5 + 1.0;       /* converges to 2 */
    }
    printf("%.10e\n", x);
    return 0;
}
