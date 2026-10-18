// Tagless hospital: 55 x 45 x 22 mm limit; flat bed at z=0.
$fn=48;
union() {
  linear_extrude(3) polygon([[-27.5,-9],[-10,-9],[-10,-22.5],[10,-22.5],[10,-9],[27.5,-9],[27.5,9],[10,9],[10,22.5],[-10,22.5],[-10,9],[-27.5,9]]);
  // Low central building supports a large roof cross.
  translate([-16,-13,0]) cube([32,26,7]);
  linear_extrude(22) union() {
    square([10,34],center=true);
    square([40,10],center=true);
  }
}
