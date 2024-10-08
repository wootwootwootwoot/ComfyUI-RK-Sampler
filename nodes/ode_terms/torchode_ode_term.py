import torch


class TorchODEODETerm:
    def __init__(
        self,
        model,
        c_device,
        c_dtype,
        o_device,
        o_dtype,
        o_shape,
        min_sigma,
        t_max,
        t_min,
        n_steps,
        progress_bar,
        p_bar_fmt,
        p_bar_pf,
        step_size_controller,
        extra_args=None,
        callback=None,
    ):
        self.model = model
        self.c_device = c_device
        self.c_dtype = c_dtype
        self.o_device = o_device
        self.o_dtype = o_dtype
        self.o_shape = o_shape
        self.min_sigma = min_sigma
        self.t_max = t_max
        self.t_min = t_min
        self.n_steps = n_steps
        self.progress_bar = progress_bar
        self.p_bar_fmt = p_bar_fmt
        self.p_bar_pf = p_bar_pf
        self.step_size_controller = step_size_controller
        self.extra_args = extra_args or {}
        self.callback = callback
        self.n_callbacks = 0
        self.step = 0
        self.last_t = None
        self.last_denoised = None

    def trigger_callback(self, t, y):
        y = y.reshape(self.o_shape)
        mask = self.last_t <= self.min_sigma
        self.n_callbacks += 1
        t = t.mean().item()

        if self.step_size_controller == "adaptive_pid":
            progress = (self.t_max - t) / (self.t_max - self.t_min)
            percentage = progress * 100
            self.progress_bar.update(percentage - self.step)
            self.progress_bar.set_postfix(self.p_bar_pf(t))
            self.progress_bar.bar_format = self.p_bar_fmt(self.n_callbacks)
            self.progress_bar.refresh()
            self.step = percentage
            i = round(progress * self.n_steps)
        elif self.step_size_controller == "fixed_scheduled":
            self.progress_bar.update(1)
            self.progress_bar.set_postfix(self.p_bar_pf(t))
            self.progress_bar.refresh()
            self.step += 1
            i = self.step

        if self.callback is not None:
            samples = torch.where(
                mask.view(*mask.shape, 1, 1, 1),
                y,
                self.last_denoised,
            )
            samples = samples.to(self.o_device, dtype=self.o_dtype)
            self.callback(
                {
                    "x": samples,
                    "i": i - 1,
                    "sigma": t,
                    "sigma_hat": t,
                    "denoised": samples,
                }
            )

    def __call__(self, t, y):
        y = y.reshape(self.o_shape)
        mask = t <= self.min_sigma

        denoised = torch.zeros_like(y)
        if not mask.all():
            y_model = y.to(self.o_device, dtype=self.o_dtype)
            t_model = t.to(self.o_device, dtype=self.o_dtype)
            denoised_model = self.model(y_model[~mask], t_model[~mask], **self.extra_args)
            denoised[~mask] = denoised_model.to(self.c_device, dtype=self.c_dtype)

        d = torch.where(
            mask.view(*mask.shape, 1, 1, 1),
            torch.zeros_like(y),
            (y - denoised) / t.view(*t.shape, 1, 1, 1),
        )

        self.last_t = t
        self.last_denoised = denoised
        return d.flatten(start_dim=1)
