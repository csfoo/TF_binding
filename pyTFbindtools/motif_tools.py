import sys

import math

import numpy

from scipy.optimize import brute, bisect

from collections import defaultdict

T = 300
R = 1.987e-3 # in kCal/mol*K
#R = 8.314e-3 # in kJ

REG_LEN = 100000

base_map = {'A': 0, 'C': 1, 'G': 2, 'T': 3}
RC_base_map = {'A': 3, 'C': 2, 'G': 1, 'T': 0}

def logit(x):
    return math.log(x) - math.log(1-x)

def logistic(x):
    try: e_x = math.exp(-x)
    except: e_x = numpy.exp(-x)
    return 1/(1+e_x)
    #return e_x/(1+e_x)

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

class DeltaDeltaGArray(numpy.ndarray):
    def calc_ddg(self, coded_subseq):
        """Calculate delta delta G for coded_subseq.
        """
        return self[coded_subseq].sum()

    def calc_base_contributions(self):
        base_contribs = numpy.zeros((len(self)/3, 4))
        base_contribs[:,1:4] = self.reshape((len(self)/3,3))
        return base_contribs
    
    def calc_min_energy(self, ref_energy):
        base_contribs = self.calc_base_contributions()
        return ref_energy + base_contribs.min(1).sum()

    def calc_max_energy(self, ref_energy):
        base_contribs = self.calc_base_contributions()
        return ref_energy + base_contribs.max(1).sum()

    @property
    def motif_len(self):
        return len(self)/3

    def consensus_seq(self):
        base_contribs = self.calc_base_contributions()
        return "".join( 'ACGT'[x] for x in numpy.argmin(base_contribs, axis=1) )

class Motif():
    def __len__(self):
        return self.length

    def iter_pwm_score(self, seq):
        seq = seq.upper()
        for offset in xrange(len(seq) - len(self)+1):
            subseq = seq[offset:offset+len(self)]
            assert len(self) == len(subseq)
            score = 0.0
            RC_score = 0.0
            if 'N' in subseq: 
                yield offset + len(self)/2, False, 0.25*len(self)
                continue
            for i, base in enumerate(subseq):
                score += self.pwm[i][base_map[base]]
                RC_score += self.pwm[len(self)-i-1][RC_base_map[base]]
            RC = True if RC_score > score else False 
            yield offset, RC, max(score, RC_score)

    def iter_seq_score(self, seq):
        for offset in xrange(len(seq) - len(self)+1):
            subseq = seq[offset:offset+len(self)]
            assert len(self) == len(subseq)
            score = self.consensus_energy
            RC_score = self.consensus_energy
            if 'N' in subseq:
                yield offset, False, self.mean_energy
                continue
            for i, base in enumerate(subseq):
                if isinstance(subseq, str): base = base_map[base]
                score += self.motif_data[i][base]
                RC_score += self.motif_data[len(self)-i-1][3-base]
                #score += self.motif_data[i][base_map[base]]
                #RC_score += self.motif_data[len(self)-i-1][RC_base_map[base]]
            assert self.consensus_energy-1e-6 <= score <= self.max_energy+1e-6
            assert self.consensus_energy-1e-6 <= RC_score <= self.max_energy+1e-6
            RC = True if RC_score < score else False 
            yield offset, RC, min(score, RC_score)
            #yield offset, False, score

    def score_seq(self, seq):
        try: assert len(seq) >= len(self)
        except: 
            print seq
            raise
        return min(x[2] for x in self.iter_seq_score(seq))
    
    def est_occ(self, unbnd_tf_conc, seq):
        score = self.score_seq(seq)
        return logistic((unbnd_tf_conc - score)/(R*T))
    
    def build_occupancy_weights(self):
        for i, weights in enumerate(self.pwm):
            row = numpy.array([-logit(1e-3/2 + (1-1e-3)*x) 
                               for x in weights])
            min_val = row.min()
            self.consensus_energy += min_val
            row -= min_val
            self.motif_data[i, :] = row

        self.mean_energy = -2/(R*T)
        self.consensus_energy = (-2 + -1.5*len(self.pwm))/(R*T)        
        mean_energy_diff = sum(row.sum()/4 for row in self.motif_data)

        # mean_energy = self.consensus_energy + mean_energy_diff/scale
        # scale =  R*T*(self.consensus_energy + mean_energy_diff)/mean_energy
        scale = mean_energy_diff/(self.mean_energy - self.consensus_energy)
        self.motif_data /= scale
        
        # change the units
        self.consensus_energy *= (R*T)
        self.mean_energy *= (R*T)
        self.motif_data *= (R*T)

        assert self.min_energy == self.consensus_energy
        #print "Conc:", self.consensus_energy, logistic(-self.consensus_energy/(R*T))
        #print "Mean:", self.mean_energy, logistic(-self.mean_energy/(R*T))
        #print self.motif_data
        #assert False

    @property
    def min_energy(self):
        return self.consensus_energy + sum(x.min() for x in self.motif_data)

    @property
    def max_energy(self):
        return self.consensus_energy + self.motif_data.max(1).sum()

    def build_ddg_array(self):
        ref_energy = self.consensus_energy
        energies = numpy.zeros(3*len(self), dtype='float32')
        for i, base_energies in enumerate(self.motif_data):
            for j, base_energy in enumerate(base_energies[1:]):
                energies[3*i+j] = base_energy - base_energies[0]
            ref_energy += base_energies[0]
        return ref_energy, energies.view(DeltaDeltaGArray)

    def update_energy_array(self, ddg_array, ref_energy):
        assert self.motif_data.shape == ddg_array.shape
        self.motif_data = ddg_array.copy()
        self.consensus_energy = ref_energy
        # normalize so that the consensus base is zero at each position 
        for base_pos, base_data in enumerate(self.motif_data):
            min_energy = base_data.min()
            self.motif_data[base_pos,:] -= min_energy
            self.consensus_energy -= min_energy
        # update the mean energy
        self.mean_energy = self.consensus_energy + self.motif_data.mean()
        return
    
    def __str__():
        pass

    def __init__(self, name, factor, pwm):
        self.name = name
        self.factor = factor
        
        self.lines = None
        self.meta_data_line = None

        self.length = len(pwm)

        self.consensus_energy = 0.0
        self.motif_data = numpy.zeros((self.length, 4), dtype='float32')
                
        self.pwm = numpy.array(pwm, dtype='float32')
        
        self.build_occupancy_weights()
        return

def load_motif_from_text(text):
    # load the motif data
    lines = text.strip().split("\n")
    if lines[0][0] == '>': lines[0] = lines[0][1:]
    name = lines[0].split()[0]
    factor = name.split("_")[0]
    motif_length = len(lines)-1

    pwm = numpy.zeros((motif_length, 4), dtype=float)

    for i, line in enumerate(lines[1:]):
        pwm_row = numpy.array([
            float(x) for x in line.split()[1:]])
        pwm[i, :] = pwm_row

    motif = Motif(name, factor, pwm)
    motif.lines = lines
    motif.meta_data_line = lines[0]

    return motif

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

def iter_motifs(fp):
    fp.seek(0)
    raw_motifs = fp.read().split(">")
    motifs = defaultdict(list)
    for motif_str in raw_motifs:
        #yield motif_str.split("\n")[0]
        if len(motif_str) == 0: continue
        yield load_motif_from_text(motif_str)
    return 

def load_motifs(fname, motif_list=None):
    if motif_list != None:
        motif_list = set(x.upper() for x in motif_list)
    obs_factors = set()
    grpd_motifs = defaultdict(list)
    with open(fname) as fp:
        for motif in iter_motifs(fp):
            obs_factors.add(motif.factor)
            if motif_list != None and motif.factor.upper() not in motif_list:
                continue
            grpd_motifs[motif.factor].append(motif)
    
    for factor, motifs in sorted(grpd_motifs.items()):
        if any(m.meta_data_line.find('jolma') != -1 for m in motifs):
            motifs = [m for m in motifs if m.meta_data_line.find('jolma') != -1]
            for motif in motifs: motif.name += "_selex"
            grpd_motifs[factor] = motifs
            #print factor, 'SELEX'
        elif any(m.meta_data_line.find('bulyk') != -1 for m in motifs):
            motifs = [m for m in motifs if m.meta_data_line.find('bulyk') != -1]
            for motif in motifs: motif.name += "_bulyk"
            grpd_motifs[factor] = motifs
            #print factor, 'BULYK'
    
    return grpd_motifs