// FLOODSHIFT disaster START | 50 x 50 x 13 mm max
// Octagonal base, four raised alert rays, and a flat centered 30 x 30 mm ArUco pad.
$fn=48;
union(){
  cylinder(d=50,h=4,$fn=8);
  linear_extrude(4) square([30,30],center=true);
  // Cardinal alert rays are outside the ArUco square and rise to 13 mm overall.
  for(a=[0,90,180,270]) rotate([0,0,a]) translate([0,21,8.5]) cube([4,7,9],center=true);
}
