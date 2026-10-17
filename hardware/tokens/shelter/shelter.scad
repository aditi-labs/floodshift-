// FLOODSHIFT emergency shelter | 55 x 45 x 22 mm max
// Flat 30 x 30 mm centered ArUco pad; raised roof ridge stays outside the pad.
$fn=48;
union(){
  linear_extrude(3) polygon([[-27.5,-22.5],[27.5,-22.5],[27.5,12],[0,22.5],[-27.5,12]]);
  linear_extrude(3) square([30,30],center=true);
  // Raised pitched roof ridge/eaves at the north perimeter, 22 mm overall height.
  translate([-11,18.2,3]) cube([22,3,19]);
  translate([-11,21.2,3]) cube([22,1.3,19]);
}
