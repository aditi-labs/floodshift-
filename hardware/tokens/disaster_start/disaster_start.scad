// Tagless START warning token: 50 x 50 x 13 mm limit.
$fn=48;
union() {
  cylinder(d=50,h=4,$fn=8);
  // Raised warning triangle, lightning bolt, and four alert rays.
  translate([0,0,2]) linear_extrude(5) polygon([[-17,-13],[17,-13],[0,17]]);
  translate([0,0,6]) linear_extrude(7) polygon([[1,12],[-7,-1],[-1,-1],[-4,-10],[7,3],[1,3]]);
  for(a=[0,90,180,270]) rotate([0,0,a]) translate([-2,20,2]) cube([4,4,7]);
}
