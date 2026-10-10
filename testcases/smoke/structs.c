// compilercheck: category=structs safety=well_defined expect_exit=0
#include <stdio.h>

struct Point { int x; int y; };

static struct Point add(struct Point a, struct Point b) {
    struct Point r;
    r.x = a.x + b.x;
    r.y = a.y + b.y;
    return r;
}

int main(void) {
    struct Point p = {3, -4};
    struct Point q = {10, 20};
    struct Point r = add(p, q);
    printf("%d %d %d\n", r.x, r.y, (int)sizeof(struct Point) == 2 * (int)sizeof(int));
    return 0;
}
