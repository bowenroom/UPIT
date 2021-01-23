# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/03_train.cyclegan.ipynb (unless otherwise specified).

__all__ = ['CycleGANLoss', 'CycleGANTrainer', 'ShowCycleGANImgsCallback', 'combined_flat_anneal', 'cycle_learner']

# Cell
from fastai.vision.all import *
from fastai.basics import *
from typing import List
from fastai.vision.gan import *
from ..models.cyclegan import *
from ..data.unpaired import *

# Cell
class CycleGANLoss(nn.Module):
    """
    CycleGAN loss function. The individual loss terms are also atrributes of this class that are accessed by fastai for recording during training.

    Attributes: \n
    `self.cgan` (`nn.Module`): The CycleGAN model. \n
    `self.l_A` (`float`): lambda_A, weight of domain A losses. \n
    `self.l_B` (`float`): lambda_B, weight of domain B losses. \n
    `self.l_idt` (`float`): lambda_idt, weight of identity lossees. \n
    `self.crit` (`AdaptiveLoss`): The adversarial loss function (either a BCE or MSE loss depending on `lsgan` argument) \n
    `self.real_A` and `self.real_B` (`fastai.torch_core.TensorImage`): Real images from domain A and B. \n
    `self.id_loss_A` (`torch.FloatTensor`): The identity loss for domain A calculated in the forward function \n
    `self.id_loss_B` (`torch.FloatTensor`): The identity loss for domain B calculated in the forward function \n
    `self.gen_loss` (`torch.FloatTensor`): The generator loss calculated in the forward function \n
    `self.cyc_loss` (`torch.FloatTensor`): The cyclic loss calculated in the forward function
    """


    def _create_gan_loss(self, loss_func):
        """
        Create adversarial loss function. It takes in an existing loss function (like those from torch.nn.functional), and returns a
        loss function that allows comparison between discriminator output feature map, and single values (0 or 1 for real and fake)
        """
        def gan_loss_func(output, target):
            return loss_func(output, torch.Tensor([target]).expand_as(output).to(output.device))
        return gan_loss_func


    def __init__(self, cgan:nn.Module, l_A:float=10., l_B:float=10, l_idt:float=0.5, lsgan:bool=True):
        """
        Constructor for CycleGAN loss.

        Arguments:

        `cgan` (`nn.Module`): The CycleGAN model. \n
        `l_A` (`float`): weight of domain A losses. (default=10) \n
        `l_B` (`float`): weight of domain B losses. (default=10) \n
        `l_idt` (`float`): weight of identity losses. (default=0.5) \n
        `lsgan` (`bool`): Whether or not to use LSGAN objective. (default=True)
        """
        super().__init__()
        store_attr()
        self.crit = self._create_gan_loss(F.mse_loss if self.lsgan else F.binary_cross_entropy)

    def set_input(self, input): "set `self.real_A` and `self.real_B` for future loss calculation"; self.real_A,self.real_B = input

    def forward(self, output, target):
        """
        Forward function of the CycleGAN loss function. The generated images are passed in as output (which comes from the model)
        and the generator loss is returned.
        """
        fake_A, fake_B, idt_A, idt_B = output
        #Generators should return identity on the datasets they try to convert to
        self.id_loss_A = self.l_idt * self.l_A * F.l1_loss(idt_A, self.real_A)
        self.id_loss_B = self.l_idt * self.l_B * F.l1_loss(idt_B, self.real_B)
        #Generators are trained to trick the discriminators so the following should be ones
        self.gen_loss_A = self.crit(self.cgan.D_A(fake_A), 1)
        self.gen_loss_B = self.crit(self.cgan.D_B(fake_B), 1)
        #Cycle loss
        self.cyc_loss_A = self.l_A * F.l1_loss(self.cgan.G_A(fake_B), self.real_A)
        self.cyc_loss_B = self.l_B * F.l1_loss(self.cgan.G_B(fake_A), self.real_B)
        return self.id_loss_A+self.id_loss_B+self.gen_loss_A+self.gen_loss_B+self.cyc_loss_A+self.cyc_loss_B

# Cell
class CycleGANTrainer(Callback):
    """`Learner` Callback for training a CycleGAN model."""
    run_before = Recorder

    def __init__(self): pass

    def _set_trainable(self, disc=False):
        """Put the generators or discriminators in training mode depending on arguments."""
        def set_requires_grad(m, rg):
            for p in m.parameters(): p.requires_grad_(rg)
        set_requires_grad(self.learn.model.G_A, not disc)
        set_requires_grad(self.learn.model.G_B, not disc)
        set_requires_grad(self.learn.model.D_A, disc)
        set_requires_grad(self.learn.model.D_B, disc)
        if disc: self.opt_D.hypers = self.learn.opt.hypers

    def before_train(self, **kwargs):
        self.G_A,self.G_B = self.learn.model.G_A,self.learn.model.G_B
        self.D_A,self.D_B = self.learn.model.D_A,self.learn.model.D_B
        self.crit = self.learn.loss_func.crit
        if not getattr(self,'opt_G',None):
            self.opt_G = self.learn.opt_func(self.learn.splitter(nn.Sequential(*flatten_model(self.G_A), *flatten_model(self.G_B))), self.learn.lr)
        else:
            self.opt_G.hypers = self.learn.opt.hypers
        if not getattr(self, 'opt_D',None):
            self.opt_D = self.learn.opt_func(self.learn.splitter(nn.Sequential(*flatten_model(self.D_A), *flatten_model(self.D_B))), self.learn.lr)
        else:
            self.opt_D.hypers = self.learn.opt.hypers

        self.learn.opt = self.opt_G

    def before_batch(self, **kwargs):
        self._set_trainable()
        self._training = self.learn.model.training
        self.learn.xb = (self.learn.xb[0],self.learn.yb[0]),
        self.learn.loss_func.set_input(*self.learn.xb)

    def after_step(self):
        self.opt_D.hypers = self.learn.opt.hypers

    def after_batch(self, **kwargs):
        "Discriminator training loop"
        if self._training:
            # Obtain images
            fake_A, fake_B = self.learn.pred[0].detach(), self.learn.pred[1].detach()
            (real_A, real_B), = self.learn.xb
            self._set_trainable(disc=True)
            # D_A loss calc. and backpropagation
            loss_D_A = 0.5 * (self.crit(self.D_A(real_A), 1) + self.crit(self.D_A(fake_A), 0))
            loss_D_A.backward()
            self.learn.loss_func.D_A_loss = loss_D_A.detach().cpu()
            # D_B loss calc. and backpropagation
            loss_D_B = 0.5 * (self.crit(self.D_B(real_B), 1) + self.crit(self.D_B(fake_B), 0))
            loss_D_B.backward()
            self.learn.loss_func.D_B_loss = loss_D_A.detach().cpu()
            # Optimizer stepping (update D_A and D_B)
            self.opt_D.step()
            self.opt_D.zero_grad()
            self._set_trainable()

    def before_validate(self, **kwargs):
        self.G_A,self.G_B = self.learn.model.G_A,self.learn.model.G_B
        self.D_A,self.D_B = self.learn.model.D_A,self.learn.model.D_B
        self.crit = self.learn.loss_func.crit

# Cell
class ShowCycleGANImgsCallback(Callback):
    "Update the progress bar with input and prediction images"
    run_after,run_valid=CycleGANTrainer,False


    def __init__(self, imgA:bool=False, imgB:bool=True, show_img_interval:int=10):
        """
        If `imgA` is True, display B-to-A conversion example during training. If `imgB` is True, display A-to-B conversion example.
        Show images every `show_img_interval` epochs.
        """
        store_attr()
        assert imgA or imgB, "At least displaying one type of prediction should be enabled"
        assert show_img_interval, "Non-zero interval for showing images"


    def before_fit(self):
        self.run = not hasattr(self.learn, 'lr_finder') and not hasattr(self, "gather_preds")
        self.nb_batches = []
        self.imgs = []
        self.titles = []
        assert hasattr(self.learn, 'progress')


    def after_epoch(self):
        "Update images"
        if (self.learn.epoch+1) % self.show_img_interval == 0:
            if self.imgA: self.imgA_result = torch.cat((self.learn.xb[0][1].detach(),self.learn.pred[0].detach()),dim=-1); self.last_gen=self.imgA_result
            if self.imgB: self.imgB_result = torch.cat((self.learn.xb[0][0].detach(),self.learn.pred[1].detach()),dim=-1); self.last_gen=self.imgB_result
            if self.imgA and self.imgB : self.last_gen = torch.cat((self.imgA_result,self.imgB_result),dim=-2)
            img = TensorImage(self.learn.dls.after_batch.decode(TensorImage(self.last_gen[0]))[0])
            self.imgs.append(img)
            self.titles.append(f'Epoch {self.learn.epoch}')
            self.progress.mbar.show_imgs(self.imgs, self.titles,imgsize=10)


# Cell
def combined_flat_anneal(pct:float, start_lr:float, end_lr:float=0, curve_type:str='linear'):
    """
    Create a schedule with constant learning rate `start_lr` for `pct` proportion of the training, and a `curve_type` learning rate (till `end_lr`) for remaining portion of training.

    Arguments:
    `pct` (`float`): Proportion of training with a constant learning rate.

    `start_lr` (`float`): Desired starting learning rate, used for beginnning `pct` of training.

    `end_lr` (`float`): Desired end learning rate, training will conclude at this learning rate.

    `curve_type` (`str`): Curve type for learning rate annealing. Options are 'linear', 'cosine', and 'exponential'.
    """
    if curve_type == 'linear':      SchedAnneal = SchedLin
    if curve_type == 'cosine':      SchedAnneal = SchedCos
    if curve_type == 'exponential': SchedAnneal = SchedExp
    schedule = combine_scheds([pct,1-pct],[SchedNo(start_lr,start_lr),SchedAnneal(start_lr,end_lr)])
    return schedule

# Cell
@patch
def fit_flat_lin(self:Learner, n_epochs:int=100, n_epochs_decay:int=100, start_lr:float=None, end_lr:float=0, curve_type:str='linear', wd:float=None,
                 cbs=None, reset_opt=False):
    "Fit `self.model` for `n_epoch` at flat `start_lr` before `curve_type` annealing to `end_lr` with weight decay of `wd` and callbacks `cbs`."
    total_epochs = n_epochs+n_epochs_decay
    pct_start = n_epochs/total_epochs
    if self.opt is None: self.create_opt()
    self.opt.set_hyper('lr', self.lr if start_lr is None else start_lr)
    start_lr = np.array([h['lr'] for h in self.opt.hypers])
    scheds = {'lr': combined_flat_anneal(pct_start, start_lr, end_lr, curve_type)}
    self.fit(total_epochs, cbs=ParamScheduler(scheds)+L(cbs), reset_opt=reset_opt, wd=wd)

# Cell
@delegates(Learner.__init__)
def cycle_learner(dls:DataLoader, m:CycleGAN, opt_func=Adam, loss_func=CycleGANLoss, show_imgs:bool=True, imgA:bool=True, imgB:bool=True, show_img_interval:bool=10, metrics:list=[], cbs:list=[], **kwargs):
    """
    Initialize and return a `Learner` object with the data in `dls`, CycleGAN model `m`, optimizer function `opt_func`, metrics `metrics`,
    and callbacks `cbs`. Additionally, if `show_imgs` is True, it will show intermediate predictions during training. It will show domain
    B-to-A predictions if `imgA` is True and/or domain A-to-B predictions if `imgB` is True. Additionally, it will show images every
    `show_img_interval` epochs. ` Other `Learner` arguments can be passed as well.
    """
    lms = LossMetrics(['id_loss_A', 'id_loss_B','gen_loss_A','gen_loss_B','cyc_loss_A','cyc_loss_B',
                       'D_A_loss', 'D_B_loss'])
    learn = Learner(dls, m, loss_func=loss_func(m), opt_func=opt_func,
                    cbs=[CycleGANTrainer, *cbs],metrics=[*lms, *[AvgMetric(metric) for metric in [*metrics]]])
    if (imgA or imgB or show_img_interval) and not show_imgs: warnings.warn('since show_imgs is disabled, ignoring imgA, imgB and show_img_interval arguments')
    if show_imgs: learn.add_cbs(ShowCycleGANImgsCallback(imgA=imgA,imgB=imgB,show_img_interval=show_img_interval))
    learn.recorder.train_metrics = True
    learn.recorder.valid_metrics = False
    return learn