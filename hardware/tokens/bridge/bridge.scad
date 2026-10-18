// Tagless temporary bridge: 70 x 40 x 13 mm limit.
union() {
  linear_extrude(4) square([70,22],center=true);
  for(s=[-1,1]) translate([s*25,0,0]) {
    linear_extrude(4) polygon([[-7,-11],[7,-11],[10,-20],[-10,-20]]);
    mirror([0,1,0]) linear_extrude(4) polygon([[-7,-11],[7,-11],[10,-20],[-10,-20]]);
  }
  // Continuous rails and transverse deck slats replace the pad.
  for(y=[-9,9]) translate([-30,y-1.5,2]) cube([60,3,11]);
  for(x=[-24,-16,-8,0,8,16,24]) translate([x-1.5,-7.5,2]) cube([3,15,4]);
}
