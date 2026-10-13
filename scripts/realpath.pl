#!/usr/bin/perl
use strict;
use warnings;
use Cwd qw(abs_path);
use File::Spec;
my $status = 0;
for my $path (@ARGV) {
    next if $path eq '--';
    if ($path =~ /^-/) { die "realpath: unsupported option $path\n"; }
    my $resolved = abs_path($path);
    if (defined $resolved) { print "$resolved\n"; }
    else { warn "realpath: cannot resolve $path\n"; $status = 1; }
}
exit $status;
