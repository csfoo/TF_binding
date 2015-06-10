import sys

import math

import numpy
from scipy.optimize import brute, bisect

T = 300
R = 1.987e-3 # in kCal
#R = 8.314e-3 # in kJ

REG_LEN = 100000

base_map = {'A': 0, 'C': 1, 'G': 2, 'T': 3}
RC_base_map = {'A': 3, 'C': 2, 'G': 1, 'T': 0}

def logit(x):
    return math.log(x) - math.log(1-x)

def logistic(x):
    try: e_x = math.exp(x)
    except: e_x = numpy.exp(x)
    return e_x/(1+e_x)

def estimate_unbnd_conc_in_region(
        motif, score_cov, atacseq_cov, chipseq_rd_cov,
        frag_len, max_chemical_affinity_change):
    # trim the read coverage to account for the motif length
    trimmed_atacseq_cov = atacseq_cov[len(motif)+1:]
    chipseq_rd_cov = chipseq_rd_cov[len(motif)+1:]

    # normalzie the atacseq read coverage
    atacseq_weights = trimmed_atacseq_cov/trimmed_atacseq_cov.max()
    
    # build the smoothing window
    sm_window = numpy.ones(frag_len, dtype=float)/frag_len
    sm_window = numpy.bartlett(2*frag_len)
    sm_window = sm_window/sm_window.sum()

    def build_occ(log_tf_conc):
        raw_occ = logistic(log_tf_conc + score_cov/(R*T))
        occ = raw_occ*atacseq_weights
        smoothed_occ = numpy.convolve(sm_window, occ/occ.sum(), mode='same')

        return raw_occ, occ, smoothed_occ

    def calc_lhd(log_tf_conc):
        raw_occ, occ, smoothed_occ = build_occ(-log_tf_conc)
        #diff = (100*smoothed_occ - 100*rd_cov/rd_cov.sum())**2
        lhd = -(numpy.log(smoothed_occ + 1e-12)*chipseq_rd_cov).sum()
        #print log_tf_conc, diff.sum()
        return lhd

    res = brute(calc_lhd, ranges=(
        slice(0, max_chemical_affinity_change, 1.0),))[0]
    log_tf_conc = max(0, min(max_chemical_affinity_change, res))
                      
    return -log_tf_conc


class Motif():
    def __len__(self):
        return self.length

    def iter_pwm_score(self, seq):
        seq = seq.upper()
        for offset in xrange(len(seq) - len(self)):
            subseq = seq[offset:offset+len(self)]
            assert len(self) == len(subseq)
            score = 0.0
            RC_score = 0.0
            if 'N' in subseq: 
                yield offset + len(self)/2, 0.25*len(self)
                continue
            for i, base in enumerate(subseq):
                score += self.pwm[i][base_map[base]]
                RC_score += self.pwm[len(self)-i-1][RC_base_map[base]]
            yield offset + len(self)/2, max(score, RC_score)

    def iter_seq_score(self, seq):
        seq = seq.upper()
        for offset in xrange(len(seq) - len(self)):
            subseq = seq[offset:offset+len(self)]
            assert len(self) == len(subseq)
            score = self.consensus_energy
            RC_score = self.consensus_energy
            if 'N' in subseq:
                yield offset + len(self)/2, self.mean_energy
                continue
            for i, base in enumerate(subseq):
                score += self.motif_data[i][base_map[base]]
                RC_score += self.motif_data[len(self)-i-1][RC_base_map[base]]
            yield offset + len(self)/2, max(score, RC_score)

    
    def __init__(self, text):
        # load the motif data
        lines = text.split("\n")
        
        self.name = lines[0].split()[0][1:]
        self.factor = self.name.split("_")[0]
        self.length = len(lines)-1

        self.consensus_energy = 0.0
        self.motif_data = numpy.zeros((self.length, 4), dtype=float)
        
        self.pwm = numpy.zeros((self.length, 4), dtype=float)
        
        for i, line in enumerate(lines[1:]):
            row = numpy.array([logit(1e-3/2 + (1-1e-3)*float(x)) 
                               for x in line.split()[1:]])
            max_val = row.max()
            self.consensus_energy += max_val
            row -= max_val
            self.motif_data[i, :] = row

            pwm_row = numpy.array([
                float(x) for x in line.split()[1:]])
            self.pwm[i, :] = pwm_row
        
        # reset the consensus energy so that the strongest binder
        # has a binding occupancy of 0.999 at chemical affinity 1
        self.consensus_energy = 12.0/(R*T) #logit(consensus_occupancy)
        consensus_occupancy = logistic(self.consensus_energy)
        
        # calculate the mean binding energy
        mean_energy_diff = sum(row.sum()/4 for row in self.motif_data) 
        def f(scale):
            mean_occ = 1e-100 + logistic(
                self.consensus_energy + mean_energy_diff/scale)
            rv = math.log10(consensus_occupancy) - math.log10(mean_occ) - 6
            return rv
        res = bisect(f, 1e-1, 1e6)
        self.mean_energy = self.consensus_energy + mean_energy_diff/res
        self.motif_data = self.motif_data/res
        
        # change the units
        self.consensus_energy *= (R*T)
        self.mean_energy *= (R*T)
        self.motif_data *= (R*T)

        #print >> sys.stderr, self.factor
        #print >> sys.stderr, "Cons Energy:", self.consensus_energy
        #print >> sys.stderr, "Cons Occ:", logistic(self.consensus_energy/(R*T))
        #print >> sys.stderr, "Mean Energy:", self.mean_energy
        #print >> sys.stderr, "Mean Occ:", logistic(self.mean_energy/(R*T))
        #print >> sys.stderr, self.motif_data
        return

def build_wig(fasta, motif, region):
    chrm, start, stop, summit = region
    
    output = []

    print >> sys.stderr, "Processing %s:%i-%i\t(%i/%i)" % (
        chrm, start, stop, regions.qsize(), n_regions)
    seq = fasta.fetch(chrm, start, stop)
    max_score = -1e9
    best_pos = -1
    lines = []
    for pos, score in score_seq(seq, motif):
        score = logistic(score)
        if score > max_score:
            max_score = score
            best_pos = pos
        output.append( "%s\t%i\t%i\t%.2f\n" % (
            chrm, start + pos, start + pos + 1, score) )
    
    summit_line = "%i\t%i\t%.2f\t%.2f\n" % (
        best_pos, summit, 
        best_pos/float(stop-start), summit/float(stop-start))

    return output, summit_line

def build_wig_worker(fasta_fname, regions, motif):
    fasta = FastaFile(fasta_fname)
    n_regions = regions.qsize()
    output = []
    output_summits = []
    while not regions.empty():
        try: region = regions.get(timeout=0.1)
        except Queue.Empty: return
        region_output, summit = build_wig(fasta, motif, region)
        output.extend( region_output )
        output_summits.append(summit)
    
    ofp.write("".join(output))
    of_summits.write("".join(output))
    
    return

def build_wiggles_for_all_peaks(fasta_fname, proc_queue, binding_model):
    pids = []
    for i in xrange(24):
        pid = os.fork()
        if pid == 0:
            build_wig_worker()
            os._exit(0)
        else:
            pids.append(pid)
    for pid in pids:
        os.wait(pid, 0)

    return

def load_all_motifs(fp):
    fp.seek(0)
    raw_motifs = fp.read().split(">")
    motifs = defaultdict(list)
    for motif_str in raw_motifs:
        if len(motif_str) == 0: continue
        factor, consensus_energy, motif_data = load_motif(motif_str)
        motifs[factor].append( [consensus_energy, motif_data] )
    return motifs

def main():
    pass