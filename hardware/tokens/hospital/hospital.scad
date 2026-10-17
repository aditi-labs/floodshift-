// FLOODSHIFT hospital | 55 x 45 x 22 mm max
// Flat 30 x 30 mm centered ArUco pad. Raised medical cross sits outside it.
$fn=48;
union(){
  linear_extrude(3) polygon([[-27.5,-9],[-10,-9],[-10,-22.5],[10,-22.5],[10,-9],[27.5,-9],[27.5,9],[10,9],[10,22.5],[-10,22.5],[-10,9],[-27.5,9]]);
  // centered flat marker pad
  linear_extrude(3) square([30,30],center=true);
  // Tall cross glyph in the north arm: top-view cross, total height 22 mm.
  translate([0,18.7,0]) cube([4,7.4,22],center=true);
  translate([0,18.5,0]) cube([11,4,22],center=true);
}
