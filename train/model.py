"""This is the file for main model."""
import torch
import torch.nn as nn
from torch.autograd import Variable
import torch.nn.functional as F

from settings import use_cuda, MAX_LENGTH, LAYER_DEPTH
"""
TODO:
    Rewrite a global and local encoder by modifying its constructor
    and forward functino
"""


class docEmbedding(nn.Module):
    """The class for embedding records.

    This class is for embedding the docvec (r.t, r.e, r.m)
    into a high dimension space. A MLP with RELU will be applied
    on the concatenation of the embeddings.

    Attributes:
        embedding1: embedding for r.t
        embedding2: embedding for r.e
        embedding3: embedding for r.m
        linear: A linear layer mapping [r.t, r.e, r.m] back to one space

    """

    def __init__(self, rt_size, re_size, rm_size, embedding_dim):
        super(docEmbedding, self).__init__()
        self.embedding1 = nn.Embedding(rt_size, embedding_dim)
        self.embedding2 = nn.Embedding(re_size, embedding_dim)
        self.embedding3 = nn.Embedding(rm_size, embedding_dim)
        self.linear = nn.Linear(embedding_dim * 3, embedding_dim)

    def forward(self, rt, re, rm):
        emb_rt = self.embedding1(rt)
        emb_re = self.embedding2(re)
        emb_rm = self.embedding3(rm)

        emb_all = torch.cat([emb_rt, emb_re, emb_rm], dim=len(rt.size()))
        output = self.linear(emb_all)
        return output

    def init_weights(self):
        initrange = 0.1
        lin_layers = [self.linear]
        em_layer = [self.embedding1, self.embedding2, self.embedding3]

        for layer in lin_layers + em_layer:
            layer.weight.data.uniform_(-initrange, initrange)
            if layer in lin_layers:
                layer.bias.data.fill_(0)


class EncoderLIN(nn.Module):
    """This is the linear encoder for the box score.

    From the origin paper, they use a linear encoder instead of standard
    sequential RNN style encoder. The encoder will mean pool over the entities
    and then linearly transform the concatenation of these pooled entity
    representations to initialize the decoder.

    """
    def __init__(self, hidden_size, embedding_layer):
        super(EncoderLIN, self).__init__()
        self.hidden_size = hidden_size
        self.embedding = embedding_layer
        self.avgpool = nn.AvgPool1d(3, stride=2, padding=1)

    def forward(self, rt, re, rm, hidden):
        embedded = self.embedding(rt, re, rm)
        output = torch.cat((embedded, hidden), dim=1)
        output = self.avgpool(output.view(-1, 1, 2 * self.hidden_size))
        return output.squeeze(1)

    def initHidden(self, batch_size):
        result = Variable(torch.zeros(batch_size, self.hidden_size))
        if use_cuda:
            return result.cuda()
        else:
            return result


class GlobalEncoderLIN(nn.Module):
    """
    Global Encoder:
        h_b_g = f(h_(b-1)_g, h_b_l)
        receives: 
            1. last time stamp in for a block at local hidden state
            2. previous time stamp of global hidden state
    """
    def __init__(self, hidden_size, embedding_layer):
        super(GlobalEncoderLIN, self).__init__()
        self.hidden_size = hidden_size
        self.local_encoder = embedding_layer
        self.avgpool = nn.AvgPool1d(3, stride=2, padding=1)

    def forward(self, rt, re, rm, hidden):
        """
        Ken edited:

        """
        embedded = self.embedding(rt, re, rm)
        output = torch.cat((embedded, hidden), dim=1)
        output = self.avgpool(output.view(-1, 1, 2 * self.hidden_size))
        return output.squeeze(1)

    def initHidden(self, batch_size):
        result = Variable(torch.zeros(batch_size, self.hidden_size))
        if use_cuda:
            return result.cuda()
        else:
            return result


class HierarchicalEncoderRNN(nn.Module):
    def __init__(self, hidden_size, local_embed,):
        super(HierarchicalEncoderRNN, self).__init__()
        self.LocalEncoder = EncoderRNN(hidden_size, local_embed, LEVEL='local')
        self.GlobalEncoder = EncoderRNN(hidden_size, None, LEVEL='global')


class EncoderRNN(nn.Module):
    """Vanilla encoder using pure gru."""
    def __init__(self, hidden_size, embedding_layer, n_layers=LAYER_DEPTH, LEVEL='local'):
        super(EncoderRNN, self).__init__()
        self.LEVEL = LEVEL
        self.n_layers = n_layers
        self.hidden_size = hidden_size
        if self.LEVEL == 'local':
            self.embedding = embedding_layer
        self.gru = nn.GRU(hidden_size, hidden_size, num_layers=self.n_layers)

    def forward(self, inputs, hidden):
        # embedded is of size (n_batch, seq_len, emb_dim)
        # gru needs (seq_len, n_batch, emb_dim)
        if self.LEVEL == 'local':
            # local encoder: input is (rt, re, rm)
            embedded = self.embedding(inputs["rt"], inputs["re"], inputs["rm"])
            inp = embedded.permute(1, 0, 2)
        else:
            # global encoder: input is local_hidden_states
            inp = inputs["local_hidden_states"]
        output, hidden = self.gru(inp, hidden)

        return output, hidden

    def initHidden(self, batch_size):
        result = Variable(torch.zeros(self.n_layers, batch_size, self.hidden_size), requires_grad=False)

        if use_cuda:
            return result.cuda()
        else:
            return result

"""
Global EncoderRNN:
Ken add: 04/04/2018
"""
class GlobalEncoderRNN(nn.Module):
    """
    Global Encoder:
        h_b_g = f(h_(b-1)_g, h_b_l)
        receives: 
            1. last time stamp in for a block at local hidden state
            2. previous time stamp of global hidden state
    """
    def __init__(self, hidden_size, n_layers=LAYER_DEPTH):
        super(GlobalEncoderRNN, self).__init__()
        self.n_layers = n_layers
        self.hidden_size = hidden_size
        self.gru = nn.GRU(hidden_size, hidden_size, num_layers=self.n_layers)

    def forward(self, loc, hidden):
        """
        Args:
            loc: (block_numbers, batch, hidden_size * num_directions)
            seq_len here is block_numbers
            loc no need to permute here
        """
        # gru needs (seq_len, n_batch, emb_dim)
        output, hidden = self.gru(loc, hidden)

        return output, hidden

    def initHidden(self, batch_size):
        result = Variable(torch.zeros(self.n_layers, batch_size, self.hidden_size))

        if use_cuda:            
            return result.cuda()
        else:
            return result

class EncoderBiLSTM(nn.Module):
    """Vanilla encoder using pure LSTM."""
    def __init__(self, hidden_size, embedding_layer, n_layers=LAYER_DEPTH):
        super(EncoderBiLSTM, self).__init__()
        self.n_layers = n_layers
        self.hidden_size = hidden_size

        self.embedding = embedding_layer
        self.bilstm = nn.LSTM(hidden_size, hidden_size // 2, num_layers=n_layers, bidirectional=True)

    def forward(self, rt, re, rm, hidden):
        embedded = self.embedding(rt, re, rm)
        embedded = torch.transpose(embedded, 0, 1)
        bilstm_outs, self.hidden = self.bilstm(embedded, hidden)

        output = torch.transpose(bilstm_outs, 0, 1)
        output = torch.transpose(output, 1, 2)
        output = F.tanh(output)
        output = F.max_pool1d(output, output.size(2)).squeeze(2)

        return output, torch.transpose(bilstm_outs, 0, 1)

    def initHidden(self, batch_size):
        forward = Variable(torch.zeros(2 * self.n_layers, batch_size, self.hidden_size // 2))
        backward = Variable(torch.zeros(2 * self.n_layers, batch_size, self.hidden_size // 2))
        if use_cuda:
            return (forward.cuda(), backward.cuda())
        else:
            return (forward, backward)

class AttnDecoderRNN(nn.Module):
    def __init__(self, hidden_size, output_size, max_length=MAX_LENGTH, n_layers=LAYER_DEPTH, dropout_p=0.5):
        super(AttnDecoderRNN, self).__init__()
        self.hidden_size = hidden_size
        self.output_size = output_size
        self.n_layers = n_layers
        self.dropout_p = dropout_p
        self.max_length = max_length

        self.embedding = nn.Embedding(self.output_size, self.hidden_size)
        self.attn = nn.Linear(self.hidden_size * 2, self.max_length)
        self.attn_combine = nn.Linear(self.hidden_size * 2, self.hidden_size)
        self.dropout = nn.Dropout(self.dropout_p)
        # self.grus = []
        for i in range(self.n_layers):
            # self.grus.append(nn.GRUCell(hidden_size, hidden_size))
            self.add_module("gru" + str(i), nn.GRUCell(hidden_size, hidden_size))
        self.out = nn.Linear(self.hidden_size, self.output_size)

    def forward(self, input, hidden, encoder_outputs):
        embedded = self.embedding(input)
        embedded = self.dropout(embedded)

        # inp = embedded.permute(1,0,2)
        attn_weights = F.softmax(
            self.attn(torch.cat((embedded, hidden[-1, :, :]), dim=1)))

        attn_weights = attn_weights.unsqueeze(1)
        attn_weights = attn_weights[:, :, :encoder_outputs.size()[1]]

        attn_applied = torch.bmm(attn_weights, encoder_outputs)
        attn_applied = attn_applied.squeeze(1)

        output = torch.cat((embedded, attn_applied), dim=1)
        output = self.attn_combine(output)

        nh = Variable(torch.zeros(hidden.size()), requires_grad=False)
        if use_cuda:
            nh.cuda()

        for i in range(self.n_layers):
            output = F.relu(output)
            layer_fnc = getattr(self, "gru" + str(i))
            output = layer_fnc(output, hidden[i, :, :])
            nh[i, :, :] = output

        output = F.log_softmax(self.out(output))
        return output, nh, attn_weights

    def initHidden(self, batch_size):
        result = Variable(torch.zeros(self.n_layers, batch_size, self.hidden_size), requires_grad=False)
        if use_cuda:
            return result.cuda()
        else:
            return result


# class HierAttnDecoderRNN(nn.Module):
#     """ The class for Hierarchical decoder.
#     """
#     def __init__(self, hidden_size, output_size, max_length=MAX_LENGTH,
#                  n_layers=LAYER_DEPTH, dropout_p=0.5):
#         super(HierAttnRNN, self).__init__()
#         globaldecoder = GlobalAttnDecoderRNN(hidden_size)
#         localdecoder = LocalAttnDecoderRNN(hidden_size, output_size)

#     def forward(nn.Module):



# The hierarchical global attention
class GlobalAttnDecoderRNN(nn.Module):
    """ The class for global decoding.

    This module is for sentence-level decoding, where we calculate
    next state as S_{n}^{g} = f(S_{n-1}^{g}, S_{n-1}^{l,(T)}, C_{n}^{g})
    , and C_{n}^{g}=\sum_{j=1}^{|b|}\beta_{n,j}h_{j}^{g}

    """
    def __init__(self, hidden_size, n_layers=LAYER_DEPTH, dropout_p=0.5):
        super(GlobalAttnDecoderRNN, self).__init__()
        self.hidden_size = hidden_size
        self.n_layers = n_layers
        self.dropout_p = dropout_p

        self.attn = Attn(hidden_size)

        self.dropout = nn.Dropout(self.dropout_p)

        self.gru = nn.GRU(hidden_size * 2, hidden_size, n_layers, dropout=dropout_p)

        # for i in range(self.n_layers):
        #     self.add_module("gru" + str(i), nn.GRUCell(hidden_size * 2, hidden_size))

    def forward(self, input, hidden, encoder_outputs):

        attn_weights = self.attn(hidden[-1, :, :], encoder_outputs)

        print('global attn weight size: {}'.format(attn_weights.size()))
        print('global encoder outputs size: {}'.format(encoder_outputs.size()))

        context = torch.bmm(attn_weights, encoder_outputs)

        print('input size: {}'.format(input.size()))
        print('global context size: {}'.format(context.size()))

        output = torch.cat((input, context.squeeze(1)), dim=1)

        # nh = Variable(torch.zeros(hidden.size()))
        # if use_cuda:
        #     nh.cuda()

        print(output.size(), hidden.size())

        # To align with the library standard (seq_len, batch, input_size)
        output = output.unsqueeze(0)
        output, nh = self.gru(output, hidden)

        # for i in range(self.n_layers):
        #     layer_fnc = getattr(self, "gru" + str(i))
        #     output = layer_fnc(output, hidden[i, :, :])
        #     nh[i, :, :] = output

        return output, nh, context, attn_weights

    def initHidden(self, batch_size):
        result = Variable(torch.zeros(self.n_layers, batch_size, self.hidden_size))
        if use_cuda:
            return result.cuda()
        else:
            return result


class LocalAttnDecoderRNN(nn.Module):
    """ The class for local decoding.

    This module is for word-level decoding, where we calculate
    next state as S_{n}^{l,(t)}=f(S_{n}^{l,(t-1)}, y_{n}^{(t-1)}, C_{n}^{l,(t)})
    , and C_{n}^{g}=\sum_{j=1}^{|b|}\beta_{n,j}h_{j}^{g}

    """
    def __init__(self, hidden_size, output_size, max_length=MAX_LENGTH,
                 n_layers=LAYER_DEPTH, dropout_p=0.5):
        super(LocalAttnDecoderRNN, self).__init__()
        self.hidden_size = hidden_size
        self.output_size = output_size
        self.n_layers = n_layers
        self.dropout_p = dropout_p
        self.max_length = max_length

        self.embedding = nn.Embedding(self.output_size, self.hidden_size)
        self.attn = Attn(hidden_size)

        self.dropout = nn.Dropout(self.dropout_p)

        self.gru = nn.GRU(hidden_size * 2, hidden_size, n_layers, dropout=dropout_p)

        # for i in range(self.n_layers):
        #     self.add_module("gru" + str(i), nn.GRUCell(hidden_size * 2, hidden_size))
        
        self.out = nn.Linear(self.hidden_size, self.output_size)

    def forward(self, input, hidden, block_attn_weights, encoder_outputs, blocks):
        embedded = self.embedding(input)
        embedded = self.dropout(embedded)

        # blocks is a list storing the length for each block
        batch_size, seq_len, hidden_size = encoder_outputs.size()
        attn_weights = Variable(torch.zeros(batch_size, len(blocks)))
        block_context = torch.zeros(batch_size, len(blocks))

        # calculate for each block
        for idbk, bk in enumerate(blocks):
            st, ed = blocks[idbk], blocks[idbk + 1]
            attn_weights[:, idbk] = self.attn(hidden[-1, :, :],
                                              encoder_outputs[:, st:ed, :])
            block_context[:, idbk] = torch.bmm(attn_weights[:, idbk],
                                               encoder_outputs[:, st:ed, :])

        context = torch.bmm(block_attn_weights, block_context)
        output = torch.cat((embedded, context), dim=1)

        # To align with the library standard (seq_len, batch, input_size)
        output = output.unsqueeze(0)
        output, nh = self.gru(output, hidden)

        # nh = Variable(torch.zeros(hidden.size()))
        # if use_cuda:
        #     nh.cuda()

        # for i in range(self.n_layers):
        #     layer_fnc = getattr(self, "gru" + str(i))
        #     output = layer_fnc(output, hidden[i, :, :])
        #     nh[i, :, :] = output

        output = F.log_softmax(self.out(torch.cat((output, context), 1)))
        return output, nh, context, attn_weights

    def initHidden(self, batch_size):
        result = Variable(torch.zeros(self.n_layers, batch_size, self.hidden_size))
        if use_cuda:
            return result.cuda()
        else:
            return result


class Attn(nn.Module):
    """ The score function for the attention mechanism.

    We define the score function as the general function from Luong et al.
    Where score(s_{i}, h_{j}) = s_{i} * W * h_{j}

    """
    def __init__(self, hidden_size):
        super(Attn, self).__init__()
        self.hidden_size = hidden_size
        self.attn = nn.Linear(self.hidden_size, self.hidden_size)

    def forward(self, hidden, encoder_outputs):
        batch_size, seq_len, hidden_size = encoder_outputs.size()
        print(encoder_outputs.size())

        # Create variable to store attention energies
        attn_energies = Variable(torch.zeros(batch_size, seq_len))  # B x 1 x S
        if use_cuda:
            attn_energies = attn_energies.cuda()

        # Calculate energies for each encoder output
        for i in range(seq_len):
            attn_energies[:, i] = self.score(hidden, encoder_outputs[:, i])

        # Normalize energies to weights in range 0 to 1, resize to B x 1 x seq_len
        return F.softmax(attn_energies).unsqueeze(1)

    def score(self, hidden, encoder_output):
        print('size of hidden: {}'.format(hidden.size()))
        print('size of encoder_hidden: {}'.format(encoder_output.size()))
        energy = self.attn(encoder_output)

        # batch-wise calculate dot-product
        hidden = hidden.unsqueeze(1)
        energy = energy.unsqueeze(2)

        print('size of energy: {}'.format(energy.size()))
        energy = torch.bmm(hidden, energy)

        return energy
