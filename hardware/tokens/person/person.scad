// FLOODSHIFT person/household | 45 x 45 x 17 mm max
// Central 30 x 30 mm flat ArUco pad with a raised head/limbs visible around it.
$fn=48;
union(){
  linear_extrude(3) square([30,30],center=true);
  // Head is north of the marker square; arms extend beyond its side edges.
  translate([0,19.2,0]) cylinder(r=3.1,h=17);
  for(s=[-1,1]) translate([s*19.8,3,0]) rotate([0,0,s*12]) linear_extrude(17) square([3.5,8],center=true);
  // Legs sit below the tag pad with a clear gap.
  for(s=[-1,1]) translate([s*7,-19,0]) linear_extrude(17) square([5,6],center=true);
}
