// Tagless sleeping shelter: 55 x 45 x 22 mm limit.
union() {
  linear_extrude(3) polygon([[-27.5,-22.5],[27.5,-22.5],[27.5,12],[0,22.5],[-27.5,12]]);
  // Solid pitched tent roof rising from the bed-supported base.
  hull() {
    translate([-23,-18,2]) cube([46,28,1]);
    translate([-1.5,-18,21]) cube([3,28,1]);
  }
  translate([-8,-22,0]) cube([16,6,5]);
}
